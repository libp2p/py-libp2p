#!/usr/bin/env python3
"""
Gossipsub Examples Runner

Convenient script to run different Gossipsub examples with predefined configurations.

Usage:
    python run_examples.py --help
    python run_examples.py quick-comparison
    python run_examples.py full-comparison
    python run_examples.py v2-demo
    python run_examples.py interactive
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path


def run_command(cmd: list, description: str):
    """Run a command and handle output"""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print(f"\n✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ {description} failed with exit code {e.returncode}")
        return False
    except KeyboardInterrupt:
        print(f"\n⏹️ {description} interrupted by user")
        return False


def quick_comparison():
    """Run a quick comparison of all Gossipsub versions"""
    print("🚀 Starting Quick Gossipsub Version Comparison")
    print("This will run a 30-second comparison across all scenarios...")
    
    scenarios = ["normal", "high_churn", "spam_attack", "network_partition"]
    results = []
    
    for scenario in scenarios:
        cmd = [
            sys.executable, "version_comparison.py",
            "--scenario", scenario,
            "--duration", "30",
            "--nodes", "4",
            "--output", f"quick_{scenario}_results.json"
        ]
        
        success = run_command(cmd, f"Quick {scenario} scenario")
        results.append((scenario, success))
        
        if not success:
            print(f"⚠️ Skipping remaining scenarios due to failure")
            break
    
    # Summary
    print(f"\n{'='*60}")
    print("QUICK COMPARISON SUMMARY")
    print(f"{'='*60}")
    for scenario, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{scenario:<20} {status}")
    
    successful = sum(1 for _, success in results if success)
    print(f"\nCompleted {successful}/{len(scenarios)} scenarios successfully")


def full_comparison():
    """Run a comprehensive comparison with longer duration"""
    print("🔬 Starting Full Gossipsub Version Comparison")
    print("This will run extensive tests with longer duration...")
    
    scenarios = [
        ("normal", 60, 6),
        ("high_churn", 90, 8),
        ("spam_attack", 120, 8),
        ("network_partition", 180, 6),
    ]
    
    results = []
    
    for scenario, duration, nodes in scenarios:
        cmd = [
            sys.executable, "version_comparison.py",
            "--scenario", scenario,
            "--duration", str(duration),
            "--nodes", str(nodes),
            "--output", f"full_{scenario}_results.json",
            "--verbose"
        ]
        
        success = run_command(cmd, f"Full {scenario} scenario ({duration}s, {nodes} nodes)")
        results.append((scenario, success))
    
    # Generate combined report
    if any(success for _, success in results):
        generate_comparison_report(results)
    
    # Summary
    print(f"\n{'='*60}")
    print("FULL COMPARISON SUMMARY")
    print(f"{'='*60}")
    for scenario, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{scenario:<20} {status}")


def v2_demo():
    """Run Gossipsub 2.0 feature demonstrations"""
    print("🎯 Starting Gossipsub 2.0 Feature Demonstrations")
    
    features = [
        ("scoring", 60, "Peer Scoring (P1-P7)"),
        ("adaptive", 45, "Adaptive Gossip"),
        ("security", 90, "Security Features"),
    ]
    
    results = []
    
    for feature, duration, description in features:
        cmd = [
            sys.executable, "v2_showcase.py",
            "--mode", "demo",
            "--feature", feature,
            "--duration", str(duration),
            "--nodes", "8",
            "--output", f"v2_{feature}_monitoring.json"
        ]
        
        success = run_command(cmd, f"{description} Demo ({duration}s)")
        results.append((feature, success))
    
    # Summary
    print(f"\n{'='*60}")
    print("GOSSIPSUB 2.0 DEMO SUMMARY")
    print(f"{'='*60}")
    for feature, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{feature:<15} {status}")


def interactive_mode():
    """Run interactive showcase"""
    print("🎮 Starting Interactive Gossipsub 2.0 Showcase")
    print("This will start an interactive session where you can explore features...")
    
    cmd = [
        sys.executable, "v2_showcase.py",
        "--mode", "interactive",
        "--nodes", "6",
        "--verbose"
    ]
    
    run_command(cmd, "Interactive Gossipsub 2.0 Showcase")


def generate_comparison_report(results):
    """Generate a combined comparison report"""
    print("\n📊 Generating Combined Comparison Report...")
    
    try:
        combined_data = {
            "timestamp": time.time(),
            "scenarios": {}
        }
        
        for scenario, success in results:
            if success:
                filename = f"full_{scenario}_results.json"
                if Path(filename).exists():
                    with open(filename, 'r') as f:
                        data = json.load(f)
                        combined_data["scenarios"][scenario] = data
        
        # Save combined report
        with open("combined_comparison_report.json", 'w') as f:
            json.dump(combined_data, f, indent=2)
        
        print("✅ Combined report saved to: combined_comparison_report.json")
        
        # Generate summary statistics
        generate_summary_stats(combined_data)
        
    except Exception as e:
        print(f"⚠️ Failed to generate combined report: {e}")


def generate_summary_stats(data):
    """Generate and display summary statistics"""
    print(f"\n{'='*60}")
    print("SUMMARY STATISTICS")
    print(f"{'='*60}")
    
    try:
        for scenario, scenario_data in data["scenarios"].items():
            print(f"\n{scenario.upper()} SCENARIO:")
            print("-" * 40)
            
            metrics = scenario_data.get("metrics", {})
            
            # Find best performing version for each metric
            versions = list(metrics.keys())
            if versions:
                # Delivery rate comparison
                delivery_rates = {v: metrics[v].get("message_delivery_rate", 0) 
                                for v in versions}
                best_delivery = max(delivery_rates.items(), key=lambda x: x[1])
                print(f"Best Delivery Rate: {best_delivery[0]} ({best_delivery[1]:.1%})")
                
                # Latency comparison
                latencies = {v: metrics[v].get("average_latency_ms", float('inf')) 
                           for v in versions}
                best_latency = min(latencies.items(), key=lambda x: x[1])
                print(f"Lowest Latency: {best_latency[0]} ({best_latency[1]:.1f}ms)")
                
                # Show all versions' performance
                print("\nAll Versions Performance:")
                for version in versions:
                    m = metrics[version]
                    print(f"  {version}: "
                          f"Delivery={m.get('message_delivery_rate', 0):.1%}, "
                          f"Latency={m.get('average_latency_ms', 0):.1f}ms")
    
    except Exception as e:
        print(f"⚠️ Error generating summary stats: {e}")


def cleanup_files():
    """Clean up generated files"""
    print("🧹 Cleaning up generated files...")
    
    patterns = [
        "quick_*.json",
        "full_*.json", 
        "v2_*.json",
        "combined_*.json"
    ]
    
    import glob
    
    cleaned = 0
    for pattern in patterns:
        for file in glob.glob(pattern):
            try:
                Path(file).unlink()
                cleaned += 1
                print(f"  Removed: {file}")
            except Exception as e:
                print(f"  Failed to remove {file}: {e}")
    
    print(f"✅ Cleaned up {cleaned} files")


def main():
    parser = argparse.ArgumentParser(
        description="Gossipsub Examples Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_examples.py quick-comparison    # Quick 30s comparison
  python run_examples.py full-comparison     # Comprehensive comparison  
  python run_examples.py v2-demo            # Gossipsub 2.0 features
  python run_examples.py interactive        # Interactive exploration
  python run_examples.py cleanup            # Clean up generated files
        """
    )
    
    parser.add_argument(
        "command",
        choices=[
            "quick-comparison", "full-comparison", 
            "v2-demo", "interactive", "cleanup"
        ],
        help="Command to run"
    )
    
    args = parser.parse_args()
    
    print(f"🎯 Gossipsub Examples Runner")
    print(f"Command: {args.command}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    if args.command == "quick-comparison":
        quick_comparison()
    elif args.command == "full-comparison":
        full_comparison()
    elif args.command == "v2-demo":
        v2_demo()
    elif args.command == "interactive":
        interactive_mode()
    elif args.command == "cleanup":
        cleanup_files()
    
    print(f"\n🏁 Command '{args.command}' completed!")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()