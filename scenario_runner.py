"""
WaxPrep Automated Test Harness — Scenario Runner
Executes generated scenarios against the production Render webhook.
Handles retries, timeouts, cold starts, and progress saving.
"""

import asyncio
import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

import httpx


@dataclass
class MessageResult:
    """Result of a single message exchange."""
    message: str
    response: Optional[str] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ScenarioResult:
    """Complete result of running a scenario."""
    scenario_id: str
    passed: bool = False
    messages: List[MessageResult] = field(default_factory=list)
    failures: List[Dict[str, str]] = field(default_factory=list)
    total_latency_ms: float = 0.0
    error: Optional[str] = None
    checkpoint: bool = False


class ScenarioRunner:
    """
    Executes test scenarios by calling the Render webhook.
    Each scenario is a conversation — messages sent one at a time,
    with realistic delays, collecting responses for assertion checking.
    """
    
    def __init__(self, config):
        self.config = config
        self.base_url = config.RENDER_URL.rstrip("/")
        self.webhook_url = f"{self.base_url}{config.WEBHOOK_PATH}"
        self.health_url = f"{self.base_url}{config.HEALTH_PATH}"
        self.client = None
        self.semaphore = asyncio.Semaphore(config.CONCURRENT_SCENARIOS)
        self.results: List[ScenarioResult] = []
        self.checkpoint_file = "test_checkpoint.json"
        
    # ═══════════════════════════════════════════
    # MAIN ENTRY POINT
    # ═══════════════════════════════════════════
    
    async def run_scenarios(
        self, 
        scenarios: List[Scenario],
        checkpoint_callback=None,
        progress_callback=None,
    ) -> List[ScenarioResult]:
        """
        Run multiple scenarios concurrently.
        
        Args:
            scenarios: List of Scenario objects to execute
            checkpoint_callback: Called every N scenarios with results
            progress_callback: Called after each scenario with (completed, total)
        
        Returns:
            List of ScenarioResult objects
        """
        self.results = []
        total = len(scenarios)
        
        # Create async client with connection pooling
        async with httpx.AsyncClient(timeout=self.config.REQUEST_TIMEOUT) as client:
            self.client = client
            
            # Process scenarios in batches for checkpointing
            batch_size = self.config.CHECKPOINT_INTERVAL
            for batch_start in range(0, total, batch_size):
                batch_end = min(batch_start + batch_size, total)
                batch = scenarios[batch_start:batch_end]
                
                # Run batch concurrently
                tasks = [self._run_single_scenario(scenario) for scenario in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Process results
                for i, result in enumerate(batch_results):
                    if isinstance(result, Exception):
                        # Scenario crashed — create error result
                        scenario = batch[i]
                        error_result = ScenarioResult(
                            scenario_id=scenario.scenario_id,
                            error=str(result),
                        )
                        self.results.append(error_result)
                    else:
                        self.results.append(result)
                
                # Checkpoint
                if checkpoint_callback:
                    await checkpoint_callback(self.results)
                
                # Progress
                if progress_callback:
                    completed = batch_end
                    await progress_callback(completed, total)
        
        return self.results
    
    # ═══════════════════════════════════════════
    # SINGLE SCENARIO
    # ═══════════════════════════════════════════
    
    async def _run_single_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Execute one scenario — a conversation between a virtual student and Wax."""
        async with self.semaphore:  # Limit concurrency
            
            result = ScenarioResult(scenario_id=scenario.scenario_id)
            chat_id = self._generate_test_chat_id(scenario)
            conversation_context = {}  # Accumulated state
            
            for i, message in enumerate(scenario.messages):
                # Simulate realistic timing
                if i > 0:
                    delay = random.uniform(
                        self.config.MESSAGE_DELAY_MIN,
                        self.config.MESSAGE_DELAY_MAX
                    )
                    await asyncio.sleep(delay)
                
                # Send message and get response
                msg_result = await self._send_message(
                    chat_id=chat_id,
                    text=message,
                    conversation_context=conversation_context,
                )
                
                result.messages.append(msg_result)
                result.total_latency_ms += msg_result.latency_ms
                
                # Update conversation context from response
                if msg_result.response:
                    conversation_context["last_response"] = msg_result.response
                
                # Stop scenario early if message failed completely
                if msg_result.error and "timeout" not in str(msg_result.error).lower():
                    break
            
            return result
    
    # ═══════════════════════════════════════════
    # MESSAGE SENDING
    # ═══════════════════════════════════════════
    
    async def _send_message(
        self,
        chat_id: int,
        text: str,
        conversation_context: dict,
    ) -> MessageResult:
        """
        Send a single message to Wax via Render webhook.
        Builds the exact JSON payload Telegram would send.
        """
        msg_result = MessageResult(message=text)
        
        # Build Telegram-compatible payload
        payload = {
            "update_id": random.randint(1000000, 9999999),
            "message": {
                "message_id": random.randint(1, 9999),
                "from": {
                    "id": chat_id,
                    "is_bot": False,
                    "first_name": f"Test_Student_{chat_id}",
                },
                "chat": {
                    "id": chat_id,
                    "type": "private",
                },
                "date": int(time.time()),
                "text": text,
            }
        }
        
        # Add test mode header
        headers = {
            "Content-Type": "application/json",
            "X-Test-Mode": "true",
            "X-Test-Scenario": "automated_harness",
        }
        
        start_time = time.time()
        
        for attempt in range(self.config.RETRY_MAX + 1):
            try:
                response = await self.client.post(
                    self.webhook_url,
                    json=payload,
                    headers=headers,
                )
                
                msg_result.latency_ms = (time.time() - start_time) * 1000
                
                if response.status_code == 200:
                    # Try to extract Wax's response from the webhook
                    # The webhook returns 200 immediately — Wax's response
                    # comes via send_telegram_message. For testing, we
                    # capture what the webhook would have sent.
                    msg_result.response = f"[HTTP 200 — {len(response.text)} bytes]"
                    break
                    
                elif response.status_code == 429:
                    # Rate limited — wait and retry
                    if attempt < self.config.RETRY_MAX:
                        backoff = self.config.RETRY_BACKOFF[min(attempt, len(self.config.RETRY_BACKOFF)-1)]
                        await asyncio.sleep(backoff)
                        continue
                    else:
                        msg_result.error = "Rate limited after max retries"
                        break
                        
                elif response.status_code >= 500:
                    # Server error — retry
                    if attempt < self.config.RETRY_MAX:
                        await asyncio.sleep(2)
                        continue
                    else:
                        msg_result.error = f"Server error {response.status_code}"
                        break
                        
                else:
                    msg_result.error = f"HTTP {response.status_code}"
                    break
                    
            except httpx.TimeoutException:
                if attempt < self.config.RETRY_MAX:
                    await asyncio.sleep(5)
                    continue
                else:
                    msg_result.error = "Request timeout"
                    break
                    
            except Exception as e:
                if attempt < self.config.RETRY_MAX:
                    await asyncio.sleep(2)
                    continue
                else:
                    msg_result.error = str(e)[:200]
                    break
        
        return msg_result
    
    # ═══════════════════════════════════════════
    # INFRASTRUCTURE
    # ═══════════════════════════════════════════
    
    async def warmup(self) -> bool:
        """Ping Render to wake it up before testing."""
        async with httpx.AsyncClient(timeout=60) as client:
            for attempt in range(self.config.WARMUP_RETRIES):
                try:
                    response = await client.get(self.health_url)
                    if response.status_code == 200:
                        return True
                except Exception:
                    pass
                await asyncio.sleep(15)
        return False
    
    def _generate_test_chat_id(self, scenario: Scenario) -> int:
        """Generate a unique but deterministic chat_id for a test student."""
        # Use scenario_id hash to keep the same student across test runs
        hash_val = hash(scenario.scenario_id) % 9000000
        return 1000000 + abs(hash_val)  # Range: 1000000 - 9999999
    
    # ═══════════════════════════════════════════
    # PROGRESS & CHECKPOINTS
    # ═══════════════════════════════════════════
    
    def save_checkpoint(self, results: List[ScenarioResult]) -> None:
        """Save progress so tests can resume if interrupted."""
        checkpoint_data = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "completed_count": len(results),
            "scenario_ids": [r.scenario_id for r in results],
            "passed_count": sum(1 for r in results if r.passed),
            "failed_count": sum(1 for r in results if not r.passed and not r.error),
            "error_count": sum(1 for r in results if r.error),
        }
        
        with open(self.checkpoint_file, "w") as f:
            json.dump(checkpoint_data, f, indent=2)
    
    def load_checkpoint(self) -> Optional[dict]:
        """Load progress from last checkpoint."""
        if os.path.exists(self.checkpoint_file):
            with open(self.checkpoint_file) as f:
                return json.load(f)
        return None
    
    async def cleanup(self) -> None:
        """Close client connections."""
        if self.client:
            await self.client.aclose()
