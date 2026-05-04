"""yeehee daemon — runs on user's home PC.

Components:
- main.py     : entry point, loops + heartbeat + signal worker + mira worker
- runner.py   : single signal generation (data fetch + 9-agent debate + push)
- mira.py     : Mira chatbot job consumer
- heartbeat.py: push status to Supabase periodically
"""
