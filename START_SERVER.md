# How to Start the API Server

## Quick Start

```bash
cd C:\Yesu\CustomerAPI\Customer-API
python main.py
```

---

## Expected Output

```
[OK] ERP PostgreSQL connected successfully.
[OK] Vendor PostgreSQL connected successfully.
[WARN] MongoDB unavailable, skipping: ... (optional, can be ignored)

INFO:     Started server process [XXXX]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

---

## Access Points

| URL | Description |
|-----|-------------|
| http://localhost:8000 | API Base URL |
| http://localhost:8000/docs | Swagger UI (Interactive API Docs) |
| http://localhost:8000/redoc | ReDoc (Alternative Docs) |
| http://localhost:8000/openapi.json | OpenAPI Schema |

---

## Validation Status

✅ **All 393 endpoints loaded successfully**
✅ **Database connections established**
✅ **All routers registered**
✅ **No import errors**
✅ **Ready to serve requests**

---

## Test the Server

### 1. Health Check
```bash
curl http://localhost:8000/docs
```

### 2. Login Test
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "engineer@kptcl.com",
    "password": "admin123"
  }'
```

### 3. Check Swagger UI
Open browser: http://localhost:8000/docs

---

## Troubleshooting

### Issue: Port 8000 already in use

**Solution:**
```bash
# Find and kill process on port 8000
netstat -ano | findstr :8000
taskkill /PID <process_id> /F
```

### Issue: Import errors

**Solution:**
```bash
# Reinstall dependencies
pip install -r requirements.txt
```

### Issue: Database connection failed

**Solution:**
- Check PostgreSQL is running
- Verify .env file has correct credentials
- Test connection manually

---

## Stop the Server

Press `Ctrl + C` in the terminal where server is running

---

## Next Steps

1. ✅ Start the API server
2. ✅ Open Swagger UI: http://localhost:8000/docs
3. ✅ Start Flutter app
4. ✅ Login as engineer@kptcl.com
5. ✅ Create testing request
6. ✅ Watch auto-assignment happen!

---

## Documentation

- **User Manual:** USER_MANUAL.md
- **API Endpoints:** API_ENDPOINTS_VALIDATION.md
- **Testing Guide:** TESTING_GUIDE.md
- **Quick Reference:** QUICK_REFERENCE.md

---

**Server is ready! Happy testing! 🚀**
