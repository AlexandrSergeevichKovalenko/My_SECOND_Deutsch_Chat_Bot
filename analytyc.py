from deepseek_bot_copy import get_db_connection
import pandas as pd

async def get_success_fail_time(user_id: int, period: str = 'week') -> pd.DataFrame:
    

