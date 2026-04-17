#!/bin/bash

set -e

echo "========================================"
echo "Affiliate Image Engine - MVP Setup"
echo "========================================"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python
echo -e "${BLUE}Checking Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is not installed. Please install Python 3.10 or higher."
    exit 1
fi
echo -e "${GREEN}✓ Python found: $(python3 --version)${NC}"

# Check Node
echo -e "${BLUE}Checking Node.js...${NC}"
if ! command -v node &> /dev/null; then
    echo "Node.js is not installed. Please install Node.js 18 or higher."
    exit 1
fi
echo -e "${GREEN}✓ Node.js found: $(node --version)${NC}"

# Setup Backend
echo ""
echo -e "${BLUE}Setting up Backend...${NC}"
cd backend

# Create venv
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# Install dependencies
echo "Installing Python dependencies..."
pip install -q -r requirements.txt
echo -e "${GREEN}✓ Backend dependencies installed${NC}"

# Create .env if not exists
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo -e "${YELLOW}⚠ Please add your GEMINI_API_KEY to backend/.env${NC}"
fi

cd ..

# Setup Frontend
echo ""
echo -e "${BLUE}Setting up Frontend...${NC}"
cd frontend

# Install dependencies
if [ ! -d "node_modules" ]; then
    echo "Installing npm dependencies..."
    npm install -q
    echo -e "${GREEN}✓ Frontend dependencies installed${NC}"
else
    echo -e "${GREEN}✓ Frontend dependencies already installed${NC}"
fi

cd ..

# Summary
echo ""
echo "========================================"
echo -e "${GREEN}✓ Setup Complete!${NC}"
echo "========================================"
echo ""
echo "To start the development servers:"
echo ""
echo -e "${BLUE}Backend:${NC}"
echo "  cd backend"
echo "  source venv/bin/activate"
echo "  python -m uvicorn app.main:app --reload"
echo ""
echo -e "${BLUE}Frontend (in another terminal):${NC}"
echo "  cd frontend"
echo "  npm run dev"
echo ""
echo -e "${YELLOW}Important:${NC}"
echo "  - Add your GEMINI_API_KEY to backend/.env"
echo "  - Backend will be at http://localhost:8000"
echo "  - Frontend will be at http://localhost:3000"
echo "  - API docs at http://localhost:8000/docs"
echo ""
