from fastapi import FastAPI
from fastapi import Depends

from auth import validate_azure_token

app = FastAPI()

@app.get("/public")
async def public_endpoint():
    return {"message": "Anyone can see this!"}

@app.get("/secure")
async def secure_endpoint(token_claims: dict = Depends(validate_azure_token)):
    """
    This endpoint is fully secured. If the token is invalid, 
    FastAPI aborts early and returns a 401 Unauthorized.
    """
    # You have access to all Azure claims here (e.g., email, roles, scp)
    user_email = token_claims.get("preferred_username") or token_claims.get("email")
    
    return {
        "message": f"Hello, {user_email}! You have successfully authenticated.",
        "azure_claims": token_claims
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)