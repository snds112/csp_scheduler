import pandas as pd
from constraint import Problem

def load_existing_schedule(filepath):
    """Loads an existing schedule from either CSV or Excel."""
    if filepath.endswith('.csv'):
        df = pd.read_csv(filepath)
    elif filepath.endswith(('.xlsx', '.xls')):
        df = pd.read_excel(filepath)
    else:
        raise ValueError("Unsupported file format. Use .csv, .xlsx, or .xls")

    existing_schedule = {}
    for _, row in df.iterrows():
        existing_schedule[row['event_name']] = (
            row['day'], 
            row['time_slot'], 
            row['room']
        )
    return existing_schedule

