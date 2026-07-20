import os
from typing import Optional

import streamlit as st
from dotenv import load_dotenv
from supabase import Client, create_client


@st.cache_resource
def get_supabase() -> Optional[Client]:
    load_dotenv()

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    try:
        url = url or st.secrets["SUPABASE_URL"]
        key = key or st.secrets["SUPABASE_KEY"]
    except (KeyError, FileNotFoundError):
        pass

    if not url or not key:
        return None

    return create_client(url, key)


def is_configured() -> bool:
    return get_supabase() is not None
