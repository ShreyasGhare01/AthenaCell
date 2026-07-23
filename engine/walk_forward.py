import pandas as pd
from typing import List, Dict, Any

def generate_rolling_folds(
    start_date: str,
    end_date: str,
    train_months: int = 12,
    validate_months: int = 3,
    step_months: int = 3
) -> List[Dict[str, pd.Timestamp]]:
    """
    Generates rolling train/validate sliding window folds.

    Parameters:
        start_date: Overall start date ('YYYY-MM-DD')
        end_date: Overall end date ('YYYY-MM-DD')
        train_months: Number of months to use for training
        validate_months: Number of months to use for validation
        step_months: Slide step size in months

    Returns:
        A list of dictionaries containing:
        - 'train_start'
        - 'train_end'
        - 'val_start'
        - 'val_end'
    """
    overall_start = pd.to_datetime(start_date)
    overall_end = pd.to_datetime(end_date)

    folds = []
    current_train_start = overall_start

    while True:
        current_train_end = current_train_start + pd.DateOffset(months=train_months) - pd.Timedelta(days=1)
        current_val_start = current_train_end + pd.Timedelta(days=1)
        current_val_end = current_val_start + pd.DateOffset(months=validate_months) - pd.Timedelta(days=1)

        # Stop generating once the validation end goes beyond the overall end
        if current_val_end > overall_end:
            break

        folds.append({
            "train_start": current_train_start,
            "train_end": current_train_end,
            "val_start": current_val_start,
            "val_end": current_val_end
        })

        # Slide forward
        current_train_start = current_train_start + pd.DateOffset(months=step_months)

    return folds
