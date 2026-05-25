from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
import requests
from bs4 import BeautifulSoup
from fpdf import FPDF
import asyncio
import os
import json
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import shutil
import zipfile

app = FastAPI(title="🔥 Genesis Forge - Autonomous Money Invention Engine")
templates = Jinja2Templates(directory="templates")

# Simple persistent memory
MEMORY_FILE = "forge_memory.json"
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r") as f:
        memory = json.load(f)
else:
    memory = {"successful_ideas": [], "top_niches": ["AI productivity", "crypto psychology", "niche journaling", "meme economy", "passive automation"]}

def hunt_trends():
    trends = ["AI agents 2026", "Solana ecosystem", "digital minimalism", "meme psychology", "autonomous income"]
    try:
        r = requests.get("https://www.reddit.com/r/Entrepreneur/hot.json", headers={"User-Agent": "GenesisForgeBot"})
        if r.status_code == 200:
            data = r.json()
            trends = [post['data']['title'][:80] for post in data['data']['children'][:3]]
    except:
        pass
    return trends

def synthesize_idea(trends):
    niche = memory["top_niches"][len(memory["successful_ideas"]) % len(memory["top_niches"])]
    combo = " + ".join(trends[:2])
    title = f"{niche.title()} × {combo} Vault"
    idea = {
        "title": title,
        "description": f"Never-before-seen digital product: Complete {combo} system for {niche.lower()}. Includes 50+ custom prompts, execution planners, and monetization blueprints.",
        "why_new": f"Unique cross of {combo} — no existing product matches this exact synthesis.",
        "price_suggestion": "$12-19"
    }
    return idea

def forge_product(idea):
    # Create product PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, idea["title"], ln=1, align='C')
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, idea["description"] + "\n\n" + idea["why_new"])
    pdf.output("genesis_product.pdf")
    
    # Sales page
    sales_html = f"""
    <!DOCTYPE html>
    <html><head><title>{idea['title']}</title><style>body{{font-family:Arial;background:#0a0a0a;color:#0f0;padding:40px;}}</style></head>
    <body>
        <h1>{idea['title']}</h1>
        <p>{idea['description']}</p>
        <p><strong>Why it's new:</strong> {idea['why_new']}</p>
        <h2>Price: {idea['price_suggestion']}</h2>
        <button onclick="alert('Thank you for supporting the Forge!')">Buy Now on Gumroad</button>
    </body></html>
    """
    with open("sales_page.html", "w") as f:
        f.write(sales_html)
    
    # Create ZIP bundle
    with zipfile.ZipFile("genesis_bundle.zip", "w") as zipf:
        zipf.write("genesis_product.pdf")
        zipf.write("sales_page.html")
    
    return "genesis_product.pdf", "sales_page.html", "genesis_bundle.zip"

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    trends = hunt_trends()
    idea = synthesize_idea(trends)
    files = forge_product(idea)
    
    # Evolve memory
    memory["successful_ideas"].append(idea["title"])
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f)
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "idea": idea,
        "trends": trends,
        "files": files,
        "history": memory["successful_ideas"][-5:]
    })

@app.get("/download/{filename}")
async def download(filename: str):
    if os.path.exists(filename):
        return FileResponse(filename, filename=filename)
    return {"error": "File not found"}

# Scheduler for autonomous forging
scheduler = BackgroundScheduler()
scheduler.add_job(lambda: synthesize_idea(hunt_trends()), 'interval', hours=2)
scheduler.start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
