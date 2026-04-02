import os
import toml
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

def load_keys():
    # 1. Try environment first (Codespaces)
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    # 2. If empty, try to read from Streamlit's local secret file
    if not url or not key:
        try:
            secrets = toml.load(".streamlit/secrets.toml")
            url = secrets.get("SUPABASE_URL")
            key = secrets.get("SUPABASE_KEY")
        except (FileNotFoundError, Exception):
            pass
            
    return url, key

class SupabaseBackend:
    def __init__(self):
        # 1. Get the keys using your new function
        url, key = load_keys() 
        
        # 2. Check if they exist before trying to use them
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env or secrets.toml")
            
        # 3. Initialize the client (Properly indented inside __init__)
        self.supabase: Client = create_client(url, key) 

    def push_signal(self, symbol, signal_type, price, metadata=None):
        data = {
            "symbol": symbol,
            "signal_type": signal_type,
            "price": price,
            "metadata": metadata or {}
        }
        return self.supabase.table("signals").insert(data).execute()

    def push_news(self, news_id, headline, source, posted_at, labels=None, category=None, is_critical=False, image_url=None):
        # 1. Check if record exists and its current category
        try:
            res = self.supabase.table("news").select("category").eq("id", news_id).execute()
            existing = res.data[0] if res.data else None
        except Exception as e:
            print(f"  [DB ERROR] Fetching news {news_id}: {e}")
            existing = None

        data = {
            "id": news_id,
            "headline": headline,
            "source": source,
            "posted_at": posted_at,
            "labels": labels or [],
            "is_critical": is_critical,
            "image_url": image_url
        }

        if existing:
            # If it already exists, only update category if it's currently 'others'
            if existing.get("category") == "others" and category:
                data["category"] = category
            
            # Use update instead of upsert to be safe, though upsert would also work here
            return self.supabase.table("news").update(data).eq("id", news_id).execute()
        else:
            # New record: use the provided category or default to 'others'
            data["category"] = category or "others"
            return self.supabase.table("news").insert(data).execute()

    def push_calendar(self, event_id, event_date, event_time, title, country, importance, actual=None, forecast=None, previous=None):
        try:
            res = self.supabase.table("calendar").select("country, importance").eq("id", event_id).execute()
            existing = res.data[0] if res.data else None
        except Exception as e:
            print(f"  [DB ERROR] Fetching calendar {event_id}: {e}")
            existing = None

        data = {
            "id": event_id,
            "event_date": event_date,
            "event_time": event_time,
            "title": title,
            "actual": actual,
            "forecast": forecast,
            "previous": previous
        }

        if existing:
            data["country"] = existing.get("country") or country
            data["importance"] = existing.get("importance") or importance
            return self.supabase.table("calendar").update(data).eq("id", event_id).execute()
        else:
            data["country"] = country
            data["importance"] = importance
            return self.supabase.table("calendar").insert(data).execute()

if __name__ == "__main__":
    # Test push
    # backend = SupabaseBackend()
    # backend.push_signal("AAPL", "BUY", 150.0)
    print("Supabase client initialized.")
