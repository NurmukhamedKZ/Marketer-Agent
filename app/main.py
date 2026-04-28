from fastapi import FastAPI

app = FastAPI(title="Content Marketer Agent")

@app.get("/health")
async def health() -> dict:
    return {"ok": True}
