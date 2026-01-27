import subprocess
import os
from datetime import datetime, timedelta

# Configuration
START_DATE = datetime(2023, 1, 1)
END_DATE = datetime(2024, 1, 1) # Stop before this date
REPOS = "apache/spark,pandas-dev/pandas,tensorflow/tensorflow,kubernetes/kubernetes"
OUTPUT_DIR = "/home/arav/projects/data_analytics/gharchive_parquet"

def get_month_ranges(start, end):
    current = start
    while current < end:
        # Calculate next month
        next_month = (current.replace(day=1) + timedelta(days=32)).replace(day=1)
        chunk_end = min(next_month, end)
        
        # Format strings for gharc
        # Start: YYYY-MM-01-00
        s_str = current.strftime("%Y-%m-%d-%H")
        # End: Last hour of previous step (strictly less than next month)
        # Actually gharc takes "end" as inclusive/exclusive depending on logic,
        # but safely we can just pass the first hour of the next month as the cutoff 
        # provided gharc logic is < end. 
        # Let's use the exact dates.
        e_str = chunk_end.strftime("%Y-%m-%d-%H")
        
        yield current, chunk_end, s_str, e_str
        current = next_month

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print(f"Starting Batch Process: {START_DATE.date()} to {END_DATE.date()}")
    print(f"Output: {OUTPUT_DIR}")
    
    for start_dt, end_dt, s_str, e_str in get_month_ranges(START_DATE, END_DATE):
        month_name = start_dt.strftime("%Y-%m")
        output_file = os.path.join(OUTPUT_DIR, f"gharchive_{month_name}.parquet")
        
        if os.path.exists(output_file):
            print(f"Skipping {month_name} (File exists)")
            continue
            
        print(f"\nProcessing {month_name}...")
        
        cmd = [
            "gharc", "download",
            "--start", s_str,
            "--end", e_str,
            "--repos", REPOS,
            "--output", output_file,
            "--workers", "4" # Keep it safe for long runs
        ]
        
        try:
            # Run gharc and stream output to console
            subprocess.run(cmd, check=True)
            print(f"Finished {month_name}")
        except subprocess.CalledProcessError:
            print(f"Error processing {month_name}")
            # Optional: break or continue?
            # continue 

if __name__ == "__main__":
    main()
