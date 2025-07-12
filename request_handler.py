import pandas as pd


def handle():
    """Process requests.csv into structured data.
    Args:
        return_type: "dict" for list of dicts, "df" for DataFrame
    Returns:
        Processed requests in specified format
    """
    # Read CSV
    requests = pd.read_csv("requests.csv")

    # Convert days
    def parse_days(days_str):
        if days_str == "all":
            return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        return [day.strip().lower() for day in days_str.split(",")]

    requests["days"] = requests["days_of_the_week"].apply(parse_days)

    # Define time slots
    TIME_SLOTS = {
        "morning": ["9-11", "11-1"],
        "afternoon": ["1-3", "3-5"],
        "evening": ["5-7", "7-9"],
        "all": ["9-11", "11-1", "1-3", "3-5", "5-7"]
    }

    # Map time slots 
    requests["time_slots"] = (
        requests["pref"]
        .fillna("all")
        .str.lower()
        .map(TIME_SLOTS)
    )

    # Drop columns 
    requests = requests.drop(columns=["pref", "days_of_the_week"])

    return requests.to_dict("records")