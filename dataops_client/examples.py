"""
Example usage of DataOps API Client.

This script demonstrates common usage patterns for the DataOps API Client library.
"""

from dataops_client import DataOpsClient
from dataops_client.config import ClientConfig
from datetime import datetime, timedelta
import pandas as pd


def example_1_basic_usage():
    """Example 1: Basic client initialization and station queries."""
    print("=" * 60)
    print("Example 1: Basic Usage")
    print("=" * 60)
    
    # Initialize client
    client = DataOpsClient(base_url="http://localhost:8000")
    
    # Check API health
    health = client.health_check()
    print(f"API Status: {health.get('status', 'unknown')}\n")
    
    # Get list of stations
    print("Fetching Colorado stations...")
    stations = client.get_stations(state="CO", limit=5)
    print(f"Found {stations.count} total stations (showing 5):\n")
    
    for station in stations.results:
        print(f"  {station.station_number}: {station.station_name}")
        print(f"    Location: ({station.latitude}, {station.longitude})")
        print(f"    HUC: {station.huc_code}")
        print()


def example_2_time_series_data():
    """Example 2: Retrieving time series discharge data."""
    print("=" * 60)
    print("Example 2: Time Series Data")
    print("=" * 60)
    
    client = DataOpsClient(base_url="http://localhost:8000")
    
    # Get 30 days of discharge data
    station_number = "09070500"
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    print(f"Fetching discharge data for {station_number}")
    print(f"Period: {start_date.date()} to {end_date.date()}\n")
    
    observations = client.get_station_data(
        station_number=station_number,
        start_date=start_date,
        end_date=end_date,
        data_type="daily_mean"
    )
    
    print(f"Retrieved {len(observations)} observations\n")
    
    if observations:
        print("First 5 observations:")
        for obs in observations[:5]:
            print(f"  {obs.observed_at.date()}: {obs.discharge_value} {obs.unit} ({obs.quality_code})")
        
        # Calculate statistics
        discharges = [obs.discharge_value for obs in observations]
        print(f"\nStatistics:")
        print(f"  Min: {min(discharges):.2f} cfs")
        print(f"  Max: {max(discharges):.2f} cfs")
        print(f"  Mean: {sum(discharges)/len(discharges):.2f} cfs")


def example_3_pandas_integration():
    """Example 3: Converting API data to pandas DataFrame for analysis."""
    print("\n" + "=" * 60)
    print("Example 3: Pandas Integration")
    print("=" * 60)
    
    client = DataOpsClient(base_url="http://localhost:8000")
    
    # Get data
    observations = client.get_station_data(
        station_number="09070500",
        start_date="2025-12-01",
        end_date="2026-01-17",
        data_type="daily_mean"
    )
    
    # Convert to DataFrame
    df = pd.DataFrame([
        {
            'date': obs.observed_at,
            'station': obs.station_number,
            'discharge': obs.discharge_value,
            'quality': obs.quality_code
        }
        for obs in observations
    ])
    
    print(f"\nDataFrame shape: {df.shape}")
    print(f"\nFirst 5 rows:")
    print(df.head())
    
    print(f"\nSummary statistics:")
    print(df['discharge'].describe())


def example_4_batch_queries():
    """Example 4: Querying multiple stations at once."""
    print("\n" + "=" * 60)
    print("Example 4: Batch Queries")
    print("=" * 60)
    
    client = DataOpsClient(base_url="http://localhost:8000")
    
    # Query multiple stations
    stations = ["09070500", "09085000"]
    
    print(f"Querying {len(stations)} stations...")
    
    try:
        data = client.batch_query_data(
            station_numbers=stations,
            start_date="2026-01-01",
            end_date="2026-01-17",
            data_type="daily_mean"
        )
        
        print("\nResults:")
        for station_num, observations in data.items():
            print(f"  {station_num}: {len(observations)} observations")
    except Exception as e:
        print(f"Note: Batch endpoint may not be implemented yet: {e}")
        
        # Fallback: query individually
        print("\nFalling back to individual queries...")
        for station_num in stations:
            obs = client.get_station_data(
                station_number=station_num,
                start_date="2026-01-01",
                end_date="2026-01-17",
                data_type="daily_mean"
            )
            print(f"  {station_num}: {len(obs)} observations")


def example_5_configuration_management():
    """Example 5: Managing pull configurations."""
    print("\n" + "=" * 60)
    print("Example 5: Configuration Management")
    print("=" * 60)
    
    client = DataOpsClient(base_url="http://localhost:8000")
    
    # Get all configurations
    print("Fetching pull configurations...")
    configs = client.get_configurations(limit=10)
    
    print(f"\nFound {configs.count} configurations:\n")
    
    for config in configs.results:
        status = "✓ ENABLED" if config.is_enabled else "✗ DISABLED"
        print(f"  [{config.id}] {config.name} {status}")
        print(f"      Source: {config.data_source} | Type: {config.data_type}")
        print(f"      Stations: {config.station_count}")
        if config.last_run_at:
            print(f"      Last run: {config.last_run_at}")
        print()


def example_6_caching_demo():
    """Example 6: Demonstrating client-side caching."""
    print("=" * 60)
    print("Example 6: Caching Demo")
    print("=" * 60)
    
    import time
    
    # Client with caching enabled (default)
    client = DataOpsClient(
        base_url="http://localhost:8000",
        cache_enabled=True,
        cache_ttl=60  # 1 minute cache
    )
    
    print("First request (hits API)...")
    start = time.time()
    stations1 = client.get_stations(state="CO", limit=100)
    time1 = time.time() - start
    print(f"  Retrieved {len(stations1.results)} stations in {time1:.3f}s")
    
    print("\nSecond request (from cache)...")
    start = time.time()
    stations2 = client.get_stations(state="CO", limit=100)
    time2 = time.time() - start
    print(f"  Retrieved {len(stations2.results)} stations in {time2:.3f}s")
    
    speedup = time1 / time2 if time2 > 0 else 0
    print(f"\n  Cache speedup: {speedup:.1f}x faster")
    
    # Clear cache
    print("\nClearing cache...")
    client.clear_cache()
    
    print("Third request (hits API again)...")
    start = time.time()
    stations3 = client.get_stations(state="CO", limit=100)
    time3 = time.time() - start
    print(f"  Retrieved {len(stations3.results)} stations in {time3:.3f}s")


def example_7_error_handling():
    """Example 7: Error handling best practices."""
    print("\n" + "=" * 60)
    print("Example 7: Error Handling")
    print("=" * 60)
    
    from dataops_client.exceptions import (
        NotFoundError,
        ValidationError,
        DataOpsAPIError,
    )
    
    client = DataOpsClient(base_url="http://localhost:8000")
    
    # Test 1: Invalid station number
    print("Test 1: Querying non-existent station...")
    try:
        station = client.get_station("INVALID_STATION_12345")
        print(f"  Found: {station.station_name}")
    except NotFoundError as e:
        print(f"  ✓ Caught NotFoundError: {e}")
    except DataOpsAPIError as e:
        print(f"  ✗ Other API error: {e}")
    
    # Test 2: Invalid date range
    print("\nTest 2: Invalid date range...")
    try:
        data = client.get_station_data(
            station_number="09070500",
            start_date="2026-12-31",  # End before start
            end_date="2026-01-01",
        )
        print(f"  Retrieved {len(data)} observations")
    except ValidationError as e:
        print(f"  ✓ Caught ValidationError: {e}")
    except Exception as e:
        print(f"  Note: {type(e).__name__}: {e}")


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("DataOps API Client - Example Usage")
    print("=" * 60 + "\n")
    
    try:
        example_1_basic_usage()
        example_2_time_series_data()
        
        # Only run pandas example if pandas is available
        try:
            import pandas
            example_3_pandas_integration()
        except ImportError:
            print("\n[Skipping Example 3: pandas not installed]")
        
        example_4_batch_queries()
        example_5_configuration_management()
        example_6_caching_demo()
        example_7_error_handling()
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n\nError running examples: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
