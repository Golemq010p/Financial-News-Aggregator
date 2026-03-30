import os
import requests
import json
import re
import time
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load env BEFORE backend init
load_dotenv()

from supabase_backend import SupabaseBackend
from groq import Groq

class FinancialJuiceWatcher:
    def __init__(self):
        self.backend = SupabaseBackend()
        
        # Initialize last_news_id from DB
        try:
            res = self.backend.supabase.table("news").select("id").order("id", desc=True).limit(1).execute()
            self.last_news_id = res.data[0]["id"] if res.data else 0
        except Exception as e:
            print(f"Warning: Could not fetch last_news_id from DB, starting fresh. {e}")
            self.last_news_id = 0
        self.session = requests.Session()
        self.base_url = "https://www.financialjuice.com/home"
        self.api_url = "https://live.financialjuice.com/FJService.asmx/Startup"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json; charset=utf-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.financialjuice.com/",
        }
        self.email = os.environ.get("FINANCIAL_JUICE_EMAIL")
        self.password = os.environ.get("FINANCIAL_JUICE_PASSWORD")
        self.info_token = ""
        self.cal_filters = None
        
        # Initialize Groq
        api_key = os.environ.get("GROQ_API_KEY")
        if api_key:
            try:
                self.client = Groq(api_key=api_key)
                print("--- Groq AI Client initialized ---")
            except Exception as e:
                self.client = None
                print(f"[AI ERROR] Groq Init: {e}")
        else:
            self.client = None
            print("Warning: GROQ_API_KEY not found in .env. AI categorization disabled.")

    def login(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Attempting login to FinancialJuice...")
        try:
            res = self.session.get(self.base_url, headers=self.headers)
            if res.status_code != 200:
                print(f"[ERROR] Home page error: {res.status_code}")
                return False
                
            soup = BeautifulSoup(res.text, 'html.parser')
            
            viewstate_el = soup.find('input', {'id': '__VIEWSTATE'})
            generator_el = soup.find('input', {'id': '__VIEWSTATEGENERATOR'})
            
            if not viewstate_el:
                print("[ERROR] Could not find __VIEWSTATE. Are you blocked?")
                return False
                
            viewstate = viewstate_el['value']
            generator = generator_el['value']
            
            payload = {
                'ctl00$ScriptManager1': 'ctl00$SignInSignUp$loginForm1$UpdatePanel1|ctl00$SignInSignUp$loginForm1$btnLogin',
                '__VIEWSTATE': viewstate,
                '__VIEWSTATEGENERATOR': generator,
                'ctl00$SignInSignUp$loginForm1$inputEmail': self.email,
                'ctl00$SignInSignUp$loginForm1$inputPassword': self.password,
                'ctl00$SignInSignUp$loginForm1$btnLogin': 'Login',
                '__ASYNCPOST': 'true'
            }
            
            login_headers = self.headers.copy()
            login_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            login_headers["X-MicrosoftAjax"] = "Delta=true"
            
            self.session.post(self.base_url, data=payload, headers=login_headers)
            
            # Refresh home to get the info token
            home_res = self.session.get(self.base_url, headers=self.headers)
            match = re.search(r"var\s+info\s*=\s*'([^']*)'", home_res.text)
            
            filter_match = re.search(r'var\s+UserCalFilters\s*=\s*({[^;]+});?', home_res.text)
            if filter_match:
                try:
                    self.cal_filters = json.loads(filter_match.group(1))
                    print("[OK] Extracted custom calendar filters.")
                except Exception as e:
                    print(f"  [!] Could not parse filters: {e}")
            
            if match:
                self.info_token = match.group(1)
                print(f"[OK] Successfully logged in. Token extracted.")
                return True
            else:
                print("[ERROR] Login failed: Could not find info token in page source.")
                return False
        except Exception as e:
            print(f"❌ Login error: {e}")
            return False

    def parse_time_to_iso(self, time_str):
        """Convert 'HH:MM Mon DD' to ISO 8601 string for current year."""
        try:
            # FinancialJuice uses '19:28 Mar 17' format
            dt = pd.to_datetime(time_str)
            # Ensure it's treated as UTC and has the current year (pd.to_datetime does this by default if year is missing)
            return dt.isoformat()
        except Exception as e:
            print(f"  [TIME ERROR] Could not parse '{time_str}': {e}")
            return datetime.now().isoformat()

    def categorize_batch(self, headlines):
        """Categorize a list of headlines in a single AI request to save quota."""
        if not self.client or not headlines:
            return {h: "others" for h in headlines}
        
        # Build numbered list for prompt
        list_str = "\n".join([f"{i+1}. {h}" for i, h in enumerate(headlines)])
        
        prompt = f"""Categorize each of these financial headlines into exactly one of these: 'politics', 'finance', 'company news', 'others'.
        Respond with a JSON object where keys are the numbers 1 to {len(headlines)} and values are the lowercase category names.
        Headlines:
        {list_str}
        
        Respond with ONLY the JSON object."""
        
        try:
            response = self.client.chat.completions.create(
                model='llama-3.1-8b-instant',
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            raw_text = response.choices[0].message.content.strip()
            # Clean JSON if model added markdown blocks
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].strip()
                
            cat_map = json.loads(raw_text)
            
            # Map back to headlines
            results = {}
            valid_cats = ['politics', 'finance', 'company news', 'others']
            for i, h in enumerate(headlines):
                val = str(cat_map.get(str(i+1), "others")).lower()
                # Ensure it's a valid category
                matched = "others"
                for v in valid_cats:
                    if v in val:
                        matched = v
                        break
                results[h] = matched
            return results
        except Exception as e:
            print(f"  [AI ERROR] Batch Categorization: {e}")
            return {h: "others" for h in headlines}

    def poll(self):
        info_val = f'"{self.info_token}"' if self.info_token else ""
        params = {
            "info": info_val, 
            "TimeOffset": "0",
            "oldID": "0",
            "tabID": "0",
            "TickerID": "0",
            "FeedCompanyID": "0",
            "strSearch": "",
            "extraNID": "0"
        }
        
        try:
            response = self.session.get(self.api_url, params=params, headers=self.headers, timeout=30)
            if response.status_code != 200:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Polling Error (Status {response.status_code})")
                return

            try:
                if response.text.startswith("<?xml"):
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(response.text)
                    raw_data = json.loads(root.text)
                else:
                    raw_data = response.json()
            except Exception as parse_err:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Parse Error (News): {parse_err}")
                return

            data = raw_data.get('d', raw_data)
            if isinstance(data, str):
                data = json.loads(data)
            
            news_items = data.get('News', [])
            if not news_items:
                return

            batch_max_id = max(item.get('NewsID', 0) for item in news_items)
            
            # Identify new items and collect headlines
            new_items_to_process = []
            headlines_to_cat = []
            
            for item in reversed(news_items):
                n_id = item.get('NewsID')
                if n_id and n_id > self.last_news_id:
                    new_items_to_process.append(item)
                    headlines_to_cat.append(item.get('Title', 'No Title'))
            
            if not new_items_to_process:
                if self.last_news_id != 0:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Polling: No new headlines. (Current: {batch_max_id})")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Initialized tracker with {len(news_items)} items. Latest ID: {batch_max_id}")
                self.last_news_id = batch_max_id
                return

            # Categorize in ONE AI call
            print(f"  --- Categorizing {len(headlines_to_cat)} new items... ---")
            cat_map = self.categorize_batch(headlines_to_cat)
            
            # Push to Supabase
            new_count = 0
            for item in new_items_to_process:
                headline = item.get('Title', 'No Title')
                category = cat_map.get(headline, "others")
                posted_at_raw = item.get('PostedLong')
                posted_at_iso = self.parse_time_to_iso(posted_at_raw)
                
                level = item.get('Level', '')
                is_critical = "active-critical" in level
                
                if self.backend.push_news(
                    news_id=item.get('NewsID'),
                    headline=headline,
                    source="FinancialJuice",
                    posted_at=posted_at_iso,
                    labels=item.get('Labels', []),
                    category=category,
                    is_critical=is_critical
                ):
                    new_count += 1
                    if self.last_news_id != 0:
                        print(f"  [NEW] [{category.upper()}] {headline[:60]}...")

            if new_count > 0 and self.last_news_id != 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Polling: Added {new_count} new headlines.")

            self.last_news_id = batch_max_id

        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] News Loop Exception: {e}")

    def poll_calendar(self):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Polling Economic Calendar...")
        try:
            cal_url = "https://live.financialjuice.com/FJService.asmx/GetCalendar"
            params = {
                "info": f'"{self.info_token}"',
                "TimeOffset": "0",
                "Filter": "0",
                "Country": ""
            }
            res = self.session.get(cal_url, params=params, headers=self.headers)
            
            if res.status_code == 200:
                try:
                    if res.text.strip().startswith("<?xml"):
                        import xml.etree.ElementTree as ET
                        root = ET.fromstring(res.text)
                        if not root.text:
                            print("  [!] Warning: Calendar XML payload is empty.")
                            return
                        data = json.loads(root.text)
                    else:
                        data = res.json()
                except Exception as parse_err:
                    print(f"  [Parse Error] Calendar: {parse_err}")
                    return
                
                # Handle ASP.NET 'd' wrapper
                inner = data.get('d', data)
                if isinstance(inner, str):
                    try:
                        events = json.loads(inner)
                    except:
                        events = []
                else:
                    events = inner.get('Calendar', inner) if isinstance(inner, dict) else inner
                
                if not isinstance(events, list):
                    print(f"  [!] Warning: Unexpected calendar data format. (Type: {type(events)})")
                    return

                for ev in events:
                    if self.cal_filters:
                        valid_countries = [c.get('code') for c in self.cal_filters.get('Countries', []) if c.get('code')]
                        valid_imps = [str(i.get('id')) for i in self.cal_filters.get('Imp', []) if i.get('id') is not None]
                        
                        ev_country = str(ev.get('CountryCode', ''))
                        ev_imp = str(ev.get('ImpID', ''))
                        
                        if valid_countries and ev_country not in valid_countries:
                            continue
                        if valid_imps and ev_imp not in valid_imps:
                            continue

                    imp_val = ev.get('Importance') 
                    if not imp_val:
                        imp_id = str(ev.get('ImpID', ''))
                        if imp_id == '3': imp_val = 'High'
                        elif imp_id == '2': imp_val = 'Medium'
                        elif imp_id == '1': imp_val = 'Low'
                        else: imp_val = 'Low'

                    self.backend.push_calendar(
                        event_id=ev.get('ID'),
                        event_date=ev.get('Date'),
                        event_time=ev.get('Time'),
                        title=ev.get('Title'),
                        country=ev.get('CountryCode', ev.get('Country')),
                        importance=imp_val,
                        actual=ev.get('Actual'),
                        forecast=ev.get('Forecast'),
                        previous=ev.get('Previous')
                    )
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Calendar Sync: Processed {len(events)} events.")
            else:
                print(f"  ⚠️ Calendar Sync Error: Status {res.status_code}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Calendar Error: {e}")

def main():
    watcher = FinancialJuiceWatcher()
    
    if watcher.login():
        print("Starting news polling (Every 60 seconds)...")
        print("Economic Calendar sync scheduled for the hour and half-hour marks.")
        
        # Initial sync on startup
        watcher.poll_calendar()
        last_sync_block = datetime.now().minute // 30
        
        while True:
            watcher.poll()
            
            now = datetime.now()
            current_block = now.minute // 30
            
            # Sync calendar on the 00 and 30 minute marks
            if now.minute % 30 == 0 and current_block != last_sync_block:
                watcher.poll_calendar()
                last_sync_block = current_block
                
            time.sleep(60)

if __name__ == "__main__":
    main()
