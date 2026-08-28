"""
Cost Tracking Utilities for Borges Knowledge Graph Project
Tracks token usage and USD costs for LLM API calls using LangChain callbacks.
"""

import os
import csv
from typing import Dict, Any, List
from datetime import datetime
from logger import setup_logger

logger = setup_logger(__name__)


# Pricing table (as of the provided rates)
PRICING = {
    "gpt-4.1": {
        "input": 2.00 / 1_000_000,  # $2.00 per 1M tokens
        "output": 8.00 / 1_000_000   # $8.00 per 1M tokens
    },
    "gpt-4.1-mini": {
        "input": 0.40 / 1_000_000,  # $0.40 per 1M tokens
        "output": 1.60 / 1_000_000   # $1.60 per 1M tokens
    },
    "gpt-4.1-nano": {
        "input": 0.10 / 1_000_000,  # $0.10 per 1M tokens
        "output": 0.40 / 1_000_000   # $0.40 per 1M tokens
    },
    # Add other models as needed
    "gpt-4o": {
        "input": 2.50 / 1_000_000,
        "output": 10.00 / 1_000_000
    },
    "gpt-4o-mini": {
        "input": 0.15 / 1_000_000,
        "output": 0.60 / 1_000_000
    }
}


class TokenUsageStats:
    """Class to track token usage and costs across multiple LLM calls."""

    def __init__(self, model_name: str = "gpt-4.1", stage_name: str = ""):
        """
        Initialize token usage tracker.

        Args:
            model_name: Name of the model being used for pricing calculation
            stage_name: Name of the pipeline stage (e.g., "Entity Extraction", "Merging")
        """
        self.model_name = model_name
        self.stage_name = stage_name
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_cost = 0.0
        self.call_count = 0
        self.call_details: List[Dict[str, Any]] = []
        self.start_time = datetime.now()

        logger.info(f"Initialized TokenUsageStats for {stage_name} - {model_name}")

    def add_usage(self, prompt_tokens: int, completion_tokens: int,
                  cost: float = 0.0, context: str = ""):
        """
        Add usage statistics from a single LLM call.

        Args:
            prompt_tokens: Number of input tokens
            completion_tokens: Number of output tokens
            cost: Cost of the call in USD
            context: Description of what this call was for
        """
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_tokens += (prompt_tokens + completion_tokens)
        self.total_cost += cost
        self.call_count += 1

        call_detail = {
            "stage": self.stage_name,
            "call_number": self.call_count,
            "context": context,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost": cost,
            "timestamp": datetime.now().isoformat()
        }
        self.call_details.append(call_detail)

        logger.debug(f"[{self.stage_name}] Call #{self.call_count}: {prompt_tokens} input + "
                    f"{completion_tokens} output = ${cost:.6f} ({context})")

    def calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """
        Calculate cost based on token usage and model pricing.

        Args:
            prompt_tokens: Number of input tokens
            completion_tokens: Number of output tokens

        Returns:
            Cost in USD
        """
        if self.model_name not in PRICING:
            logger.warning(f"Model {self.model_name} not in pricing table. Using default GPT-4.1 pricing.")
            pricing = PRICING["gpt-4.1"]
        else:
            pricing = PRICING[self.model_name]

        cost = (prompt_tokens * pricing["input"]) + (completion_tokens * pricing["output"])
        return cost

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics.

        Returns:
            Dictionary containing summary statistics
        """
        elapsed_time = (datetime.now() - self.start_time).total_seconds()

        summary = {
            "stage_name": self.stage_name,
            "model_name": self.model_name,
            "total_calls": self.call_count,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost,
            "avg_prompt_tokens_per_call": self.total_prompt_tokens / self.call_count if self.call_count > 0 else 0,
            "avg_completion_tokens_per_call": self.total_completion_tokens / self.call_count if self.call_count > 0 else 0,
            "avg_cost_per_call": self.total_cost / self.call_count if self.call_count > 0 else 0,
            "elapsed_time_seconds": elapsed_time
        }

        return summary

    def print_summary(self):
        """Print a formatted summary of token usage and costs."""
        summary = self.get_summary()

        print("\n" + "=" * 70)
        print(f"TOKEN USAGE SUMMARY - {self.stage_name}")
        print(f"Model: {self.model_name}")
        print("=" * 70)
        print(f"Total API Calls:          {summary['total_calls']}")
        print(f"Total Tokens:             {summary['total_tokens']:,}")
        print(f"  - Input Tokens:         {summary['total_prompt_tokens']:,}")
        print(f"  - Output Tokens:        {summary['total_completion_tokens']:,}")
        print(f"\nTotal Cost:               ${summary['total_cost_usd']:.6f}")
        print(f"\nAverages per Call:")
        print(f"  - Input Tokens:         {summary['avg_prompt_tokens_per_call']:.1f}")
        print(f"  - Output Tokens:        {summary['avg_completion_tokens_per_call']:.1f}")
        print(f"  - Cost:                 ${summary['avg_cost_per_call']:.6f}")
        print(f"\nElapsed Time:             {summary['elapsed_time_seconds']:.2f} seconds")
        print("=" * 70 + "\n")

    def export_to_csv(self, filepath: str):
        """
        Export detailed call statistics to CSV.

        Args:
            filepath: Path to save the CSV file
        """
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                if not self.call_details:
                    logger.warning("No call details to export")
                    return

                fieldnames = self.call_details[0].keys()
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                writer.writeheader()
                writer.writerows(self.call_details)

            logger.info(f"Exported {len(self.call_details)} call details to {filepath}")

        except Exception as e:
            logger.error(f"Failed to export to CSV: {str(e)}", exc_info=True)


class PipelineCostTracker:
    """Tracks costs across all pipeline stages."""

    def __init__(self):
        """Initialize pipeline cost tracker."""
        self.stage_trackers: Dict[str, TokenUsageStats] = {}
        self.start_time = datetime.now()
        logger.info("Initialized PipelineCostTracker")

    def get_or_create_tracker(self, stage_name: str, model_name: str) -> TokenUsageStats:
        """
        Get existing tracker for a stage or create a new one.

        Args:
            stage_name: Name of the pipeline stage
            model_name: Model being used

        Returns:
            TokenUsageStats instance for the stage
        """
        if stage_name not in self.stage_trackers:
            self.stage_trackers[stage_name] = TokenUsageStats(
                model_name=model_name,
                stage_name=stage_name
            )
        return self.stage_trackers[stage_name]

    def print_full_summary(self):
        """Print summary for all pipeline stages."""
        print("\n" + "=" * 70)
        print("FULL PIPELINE COST SUMMARY")
        print("=" * 70)

        total_cost = 0.0
        total_tokens = 0
        total_calls = 0

        for stage_name, tracker in self.stage_trackers.items():
            summary = tracker.get_summary()
            total_cost += summary['total_cost_usd']
            total_tokens += summary['total_tokens']
            total_calls += summary['total_calls']

            print(f"\n{stage_name} ({tracker.model_name}):")
            print(f"  Calls: {summary['total_calls']}")
            print(f"  Tokens: {summary['total_tokens']:,} (Input: {summary['total_prompt_tokens']:,}, Output: {summary['total_completion_tokens']:,})")
            print(f"  Cost: ${summary['total_cost_usd']:.6f}")

        elapsed_time = (datetime.now() - self.start_time).total_seconds()

        print("\n" + "-" * 70)
        print(f"TOTAL PIPELINE COST: ${total_cost:.6f}")
        print(f"Total Tokens: {total_tokens:,}")
        print(f"Total API Calls: {total_calls}")
        print(f"Total Time: {elapsed_time:.2f} seconds")
        print("=" * 70 + "\n")

    def export_all_to_csv(self, output_dir: str):
        """
        Export all stage details to separate CSV files.

        Args:
            output_dir: Directory to save CSV files
        """
        try:
            os.makedirs(output_dir, exist_ok=True)

            for stage_name, tracker in self.stage_trackers.items():
                # Sanitize stage name for filename
                safe_name = stage_name.replace(" ", "_").lower()
                filepath = os.path.join(output_dir, f"{safe_name}_cost_details.csv")
                tracker.export_to_csv(filepath)

            # Export summary CSV
            summary_path = os.path.join(output_dir, "pipeline_cost_summary.csv")
            with open(summary_path, 'w', newline='', encoding='utf-8') as f:
                fieldnames = ['stage_name', 'model_name', 'total_calls', 'total_tokens',
                             'total_prompt_tokens', 'total_completion_tokens', 'total_cost_usd']
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                writer.writeheader()
                for stage_name, tracker in self.stage_trackers.items():
                    summary = tracker.get_summary()
                    writer.writerow({
                        'stage_name': summary['stage_name'],
                        'model_name': summary['model_name'],
                        'total_calls': summary['total_calls'],
                        'total_tokens': summary['total_tokens'],
                        'total_prompt_tokens': summary['total_prompt_tokens'],
                        'total_completion_tokens': summary['total_completion_tokens'],
                        'total_cost_usd': summary['total_cost_usd']
                    })

            logger.info(f"Exported pipeline cost summary to {output_dir}")

        except Exception as e:
            logger.error(f"Failed to export pipeline costs: {str(e)}", exc_info=True)

    def estimate_full_corpus_cost(self, sample_files: int, total_files: int) -> Dict[str, Any]:
        """
        Estimate the cost for processing the full corpus based on sample.

        Args:
            sample_files: Number of files in the sample
            total_files: Total number of files in corpus

        Returns:
            Dictionary with estimated costs
        """
        if sample_files == 0:
            logger.error("Cannot estimate with 0 sample files")
            return {}

        scaling_factor = total_files / sample_files

        estimates = {}
        total_estimated_cost = 0.0

        for stage_name, tracker in self.stage_trackers.items():
            summary = tracker.get_summary()

            stage_estimate = {
                'stage_name': stage_name,
                'model_name': tracker.model_name,
                'sample_cost': summary['total_cost_usd'],
                'estimated_total_cost': summary['total_cost_usd'] * scaling_factor,
                'sample_tokens': summary['total_tokens'],
                'estimated_total_tokens': summary['total_tokens'] * scaling_factor,
                'sample_calls': summary['total_calls'],
                'estimated_total_calls': summary['total_calls'] * scaling_factor
            }

            estimates[stage_name] = stage_estimate
            total_estimated_cost += stage_estimate['estimated_total_cost']

        estimates['total_estimated_cost'] = total_estimated_cost
        estimates['sample_files'] = sample_files
        estimates['total_files'] = total_files
        estimates['scaling_factor'] = scaling_factor

        return estimates

    def print_corpus_estimate(self, sample_files: int, total_files: int):
        """
        Print estimated costs for the full corpus.

        Args:
            sample_files: Number of files in the sample
            total_files: Total number of files in corpus
        """
        estimates = self.estimate_full_corpus_cost(sample_files, total_files)

        if not estimates:
            print("Cannot generate estimate - no data available")
            return

        print("\n" + "=" * 70)
        print(f"ESTIMATED COST FOR FULL CORPUS ({total_files} files)")
        print(f"Based on sample of {sample_files} files")
        print("=" * 70)

        for stage_name, tracker in self.stage_trackers.items():
            if stage_name in estimates:
                est = estimates[stage_name]
                print(f"\n{stage_name} ({est['model_name']}):")
                print(f"  Sample Cost: ${est['sample_cost']:.6f}")
                print(f"  Estimated Total Cost: ${est['estimated_total_cost']:.2f}")
                print(f"  Estimated Total Tokens: {est['estimated_total_tokens']:,.0f}")

        print("\n" + "-" * 70)
        print(f"TOTAL ESTIMATED COST: ${estimates['total_estimated_cost']:.2f}")
        print(f"Confidence: Based on {sample_files}/{total_files} files ({(sample_files/total_files)*100:.1f}%)")
        print("=" * 70 + "\n")


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for a given text.
    Uses a simple heuristic: ~4 characters per token for English text.

    Args:
        text: Input text

    Returns:
        Estimated token count
    """
    # Simple estimation: average of 4 characters per token
    # This is a rough estimate and may not be accurate for all texts
    estimated = len(text) // 4
    return estimated
