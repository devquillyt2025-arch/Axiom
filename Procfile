# For process managers (honcho / foreman / overmind):   honcho start
# Run `npm run setup` once first. On Windows prefer `npm run dev` (the venv path below is POSIX).
api: cd backend && .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
web: npm --prefix frontend run dev -- -p 3000
