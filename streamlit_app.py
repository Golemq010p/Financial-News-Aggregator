import streamlit as st
from streamlit_autorefresh import st_autorefresh # Make sure to pip install this too!
import pandas as pd
import time
import os
from datetime import datetime, timedelta
import pytz
from supabase_backend import SupabaseBackend
from dotenv import load_dotenv
from groq import Groq

# Load environment
load_dotenv()

# Initialize AI Client
api_key = os.environ.get("GROQ_API_KEY")
ai_client = Groq(api_key=api_key) if api_key else None

def get_ai_analysis(headline):
    if not ai_client:
        return "AI API Key not configured."
    
    prompt = f"""As a financial analyst, analyze this headline:
    "{headline}"
    
    1. What are the future implications?
    2. What impact might this have on the market?
    
    Provide a concise, professional analysis."""
    
    try:
        response = ai_client.chat.completions.create(
            model='llama-3.1-8b-instant',
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"AI Error: {e}"

# Page configuration
st.set_page_config(
    page_title="News & Economic Dashboard",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize Backend
@st.cache_resource
def get_backend():
    try:
        return SupabaseBackend()
    except Exception as e:
        st.error(f"Failed to connect to Supabase: {e}")
        return None

backend = get_backend()

# --- Custom Styling ---
st.markdown("""
    <style>
    .main {
        background-color: #0e1117;
        color: #fafafa;
    }
    .news-ticker {
        background-color: #1a1c23;
        padding: 10px;
        border-bottom: 2px solid #00ff00;
        font-family: 'Courier New', Courier, monospace;
        white-space: nowrap;
        overflow: hidden;
        margin-bottom: 20px;
    }
    .cal-card {
        background-color: #1e2130;
        padding: 10px;
        border-radius: 5px;
        border-left: 5px solid #00ff00;
        margin-bottom: 10px;
    }
    .importance-high { border-left-color: #ff4b4b; }
    .importance-medium { border-left-color: #ffa500; }
    .importance-low { border-left-color: #00ff00; }
    .critical-news {
        background-color: rgba(255, 75, 75, 0.2) !important;
        border: 1px solid #ff4b4b !important;
        border-radius: 5px;
        padding: 5px;
    }
    </style>
""", unsafe_allow_html=True)

# --- Components ---

def news_ticker():
    if not backend: return
    try:
        response = backend.supabase.table("news").select("*").eq("is_critical", True).order("id", desc=True).limit(5).execute()
        news_items = response.data
        if news_items:
            ticker_text = "  |  ".join([f"🚨 {item['headline']}" for item in news_items])
            st.markdown(f'<div class="news-ticker"><marquee scrollamount="5">{ticker_text}</marquee></div>', unsafe_allow_html=True)
    except:
        pass

def calendar_section():
    if not backend: return
    
    try:
        # Get start and end dates (next 5 days)
        now_utc = datetime.now(pytz.UTC)
        end_date = (now_utc + timedelta(days=5)).date()
        
        response = backend.supabase.table("calendar")\
            .select("*")\
            .gte("event_date", now_utc.date().isoformat())\
            .lte("event_date", end_date.isoformat())\
            .order("event_date")\
            .order("event_time")\
            .execute()
        
        events = response.data
        if not events:
            st.info("No upcoming calendar events found for the next 5 days.")
            return

        # 1. Prepare data with UTC timestamps for comparison
        df = pd.DataFrame(events)
        
        # UI Filtering
        all_countries = sorted([c for c in df['country'].unique() if c])
        
        default_countries = [c for c in ['US', 'GB', 'CH', 'JP', 'Global'] if c in all_countries]
        
        fcol1, _ = st.columns([1, 3])
        with fcol1:
            selected_countries = st.multiselect("Countries", options=all_countries, default=default_countries, label_visibility="collapsed", placeholder="🌍 Countries...")
            
        df = df[df['country'].isin(selected_countries)]
        
        if df.empty:
            st.info("No calendar events match the selected filters.")
            return
        
        def get_utc_dt(row):
            try:
                if ":" in row['event_time']:
                    dt_str = f"{row['event_date']} {row['event_time']}"
                    return datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=pytz.UTC)
            except:
                pass
            # Fallback for "All Day" or malformed time
            return datetime.strptime(row['event_date'], "%Y-%m-%d").replace(tzinfo=pytz.UTC)

        df['dt_utc'] = df.apply(get_utc_dt, axis=1)
        now_utc = datetime.now(pytz.UTC)
        
        # Find the single "NEXT" event (the first one that hasn't happened yet)
        future_events = df[df['dt_utc'] >= now_utc].sort_values('dt_utc')
        next_event_id = future_events.iloc[0]['id'] if not future_events.empty else None

        def to_eastern_date(row):
            eastern = pytz.timezone('America/New_York')
            return row['dt_utc'].astimezone(eastern).strftime('%a, %b %d')

        df['display_date'] = df.apply(to_eastern_date, axis=1)
        
        unique_dates = df['display_date'].unique()
        cols = st.columns(len(unique_dates))
        
        for idx, date_str in enumerate(unique_dates):
            with cols[idx]:
                st.markdown(f"#### 📌 {date_str}")
                
                with st.container(height=400, border=False):
                    group = df[df['display_date'] == date_str]
                    
                    for _, row in group.iterrows():
                        is_next = (row['id'] == next_event_id)
                        is_past = (row['dt_utc'] < now_utc)
                        
                        # Style logic
                        opacity = "0.6" if is_past else "1.0"
                        bg_style = "background-color: #1e2130;"
                        
                        # Importance color
                        imp_color = "#00ff00" # Low
                        if row['importance'] == 'High': imp_color = "#ff4b4b"
                        elif row['importance'] == 'Medium': imp_color = "#ffa500"
                        
                        container_style = f"{bg_style} opacity: {opacity}; border-left: 4px solid {imp_color};"
                        
                        # Special NEXT highlight
                        if is_next:
                            container_style = f"background-color: #2a2d3e; border: 2px solid #ffd700; border-left: 8px solid {imp_color};"
                        
                        # Convert display time to Eastern
                        eastern = pytz.timezone('America/New_York')
                        display_time_est = row['dt_utc'].astimezone(eastern).strftime("%H:%M")
                        if row['event_time'] == "All Day": display_time_est = "All Day"

                        next_badge = '<span style="background-color: #ffd700; color: black; padding: 2px 5px; border-radius: 3px; font-size: 0.7rem; font-weight: bold; margin-left: 10px;">NEXT EVENT</span>' if is_next else ""

                        st.markdown(f"""
                            <div style="{container_style} padding: 6px 10px; border-radius: 5px; margin-bottom: 8px; position: relative;">
                                <div style="display: flex; align-items: baseline; justify-content: space-between; gap: 8px;">
                                    <div style="display: flex; align-items: baseline; gap: 8px; overflow: hidden; flex-grow: 1;">
                                        <span style="font-size: 0.85rem; color: #ffd700; font-weight: bold; flex-shrink: 0;">{display_time_est}</span>
                                        <span style="font-size: 0.9rem; font-weight: bold; color: #ffffff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{row['title']} {next_badge}</span>
                                    </div>
                                    <div style="font-size: 0.8rem; color: {'#dddddd' if is_past else '#ffffff'}; flex-shrink: 0; white-space: nowrap;">
                                        A: <span style="font-weight: 800;">{row['actual'] or '-'}</span> | 
                                        F: <span style="font-weight: 800;">{row['forecast'] or '-'}</span>
                                    </div>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)

    except Exception as e:
        st.error(f"Error loading calendar: {e}")

def news_table():
    col1, col2 = st.columns([2, 1])
    with col1:
        st.header("📰 Latest Financial Headlines")
    
    with col2:
        available_cats = ['All', 'Critical', 'politics', 'finance', 'company news', 'others']
        selected_cat = st.selectbox(
            "Filter Category:", 
            available_cats, 
            index=0,
            help="Filter by AI-assigned category"
        )
    
    # Session state for news loading limit
    if 'news_limit' not in st.session_state:
        st.session_state.news_limit = 100

    # Calculate start of today (Eastern) in UTC
    try:
        eastern = pytz.timezone('America/New_York')
        now_est = datetime.now(eastern)
        today_start_est = now_est.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_est.astimezone(pytz.utc).isoformat()
        
        query = backend.supabase.table("news").select("*").order("id", desc=True)
        
        if selected_cat == 'All':
            query = query.limit(st.session_state.news_limit)
        elif selected_cat == 'Critical':
            query = query.eq('is_critical', True).gte('posted_at', today_start_utc).limit(1000)
        else:
            # Fetch ALL matching headlines for the day (UTC today)
            query = query.eq('category', selected_cat).gte('posted_at', today_start_utc).limit(1000)
            
        response = query.execute()
        df = pd.DataFrame(response.data)
        
        if not df.empty:
            if 'category' not in df.columns:
                df['category'] = 'others'
            
            if 'posted_at' in df.columns:
                # Use format='mixed' to handle both ISO and old 'HH:MM Mon DD' without warnings
                df['posted_at'] = pd.to_datetime(df['posted_at'], format='mixed', errors='coerce', utc=True)
                eastern = pytz.timezone('America/New_York')
                df['display_time'] = df['posted_at'].dt.tz_convert(eastern).dt.strftime('%H:%M:%S')

            # Render News Rows
            # Header Row
            hcol1, hcol2, hcol3, hcol4 = st.columns([1, 1, 4, 1.5])
            hcol1.markdown("**Time (ET)**")
            hcol2.markdown("**AI Cat**")
            hcol3.markdown("**Headline**")
            hcol4.markdown("**Analysis**")
            st.markdown("---")

            # Session state for AI answers and active item
            if 'ai_answers' not in st.session_state:
                st.session_state.ai_answers = {}
            if 'active_ai_id' not in st.session_state:
                st.session_state.active_ai_id = None

            for idx, row in df.iterrows():
                row_id = row['id']
                rcol1, rcol2, rcol3, rcol4 = st.columns([1, 1, 4, 1.5])
                
                rcol1.write(f"_{row['display_time']}_")
                
                cat_color = {
                    'politics': '#ff4b4b',
                    'finance': '#00ffc8',
                    'company news': '#1c83e1',
                    'others': '#888888'
                }.get(row['category'], '#888888')
                
                # Check for critical status
                is_crit = row.get('is_critical', False)
                hl_style = ' style="background-color: rgba(255, 75, 75, 0.2); padding: 5px; border-radius: 5px; border: 1px solid #ff4b4b;"' if is_crit else ""
                hl_prefix = "🚨 " if is_crit else ""

                has_image = 'image_url' in row and pd.notna(row.get('image_url')) and str(row.get('image_url')).strip() and str(row.get('image_url')) != 'None'
                img_tag = f'<br><img src="{row.get("image_url")}" style="max-width: 100%; border-radius: 5px; margin-top: 10px; border: 1px solid #333;">' if has_image else ""

                rcol2.markdown(f'<span style="color: {cat_color}; font-weight: bold; font-size: 0.8rem;">{row["category"].upper()}</span>', unsafe_allow_html=True)
                rcol3.markdown(f'<div{hl_style}>{hl_prefix}**{row["headline"]}**{img_tag}</div>', unsafe_allow_html=True)
                
                # Logic for "Analyzed" marker (highlight only when collapsed)
                is_analyzed = row_id in st.session_state.ai_answers
                is_active = st.session_state.active_ai_id == row_id
                
                # We want to "mark" it (blue border) only after it's been analyzed AND collapsed
                show_marker = is_analyzed and not is_active
                button_key = f"ai_btn_{row_id}"
                
                if show_marker:
                    # Inject style targeted to this specific button's container
                    st.markdown(f"""
                        <style>
                        div#btn-container-{row_id} button {{
                            border: 2px solid #007bff !important;
                            box-shadow: 0 0 8px rgba(0,123,255,0.4) !important;
                        }}
                        </style>
                    """, unsafe_allow_html=True)

                # Ask AI Button Wrapper
                with rcol4:
                    st.markdown(f'<div id="btn-container-{row_id}">', unsafe_allow_html=True)
                    if st.button("Ask an AI 🤖", key=button_key, use_container_width=True):
                        if st.session_state.active_ai_id == row_id:
                            st.session_state.active_ai_id = None # Toggle Close
                        else:
                            st.session_state.active_ai_id = row_id # Open
                            if row_id not in st.session_state.ai_answers:
                                with st.spinner("Analyzing..."):
                                    answer = get_ai_analysis(row['headline'])
                                    st.session_state.ai_answers[row_id] = answer
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)
                
                # Show answer only if ACTIVE
                if is_active and is_analyzed:
                    st.info(st.session_state.ai_answers[row_id])
                
                st.markdown('<div style="margin-bottom: 5px; border-bottom: 1px solid #333;"></div>', unsafe_allow_html=True)

            # Infinite Scroll Load More
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄 Click to Load More Headlines...", use_container_width=True):
                st.session_state.news_limit += 100
                st.rerun()

        else:
            st.info("No news headlines found yet.")
    except Exception as e:
        st.warning(f"Could not fetch news: {e}")

# --- Main Layout ---

def main():
    # Run this every 60 seconds to refresh the UI and fetch new data from Supabase
    st_autorefresh(interval=60 * 1000, key="datarefresh")

    st.title("Financial News Aggregator Dashboard")
    
    news_ticker()
    
    with st.expander("📅 Economic Calendar (Next 5 Days)", expanded=False):
        calendar_section()
        
    with st.expander("📈 Earnings Hub Calendar", expanded=False):
        st.components.v1.html(
            """
            <iframe
              src="https://earningshub.com/embed/calendar?theme=dark&calendarView=week&filter=popular"
              title="Earnings Hub Calendar"
              style="width: 100%; height: 600px; border: none;"
            ></iframe>
            """,
            height=600,
        )
    
    st.write("---")
    
    news_table()

    if st.button("Refresh Now"):
        st.rerun()

    #time.sleep(15)
    #st.rerun()

if __name__ == "__main__":
    main()
