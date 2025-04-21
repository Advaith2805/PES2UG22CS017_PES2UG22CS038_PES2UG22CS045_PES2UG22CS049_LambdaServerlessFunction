# Lambda - Serverless Function Execution Platform

## Project Description
Lambda is a lightweight serverless function execution platform that allows users to deploy and run functions in an isolated environment. It supports multiple virtualization technologies like Docker and Firecracker to ensure efficient and secure execution.

## Team Members
- ABHINAV SANKARSHANA DASU
- ADVAITH B
- AKEPATI RAMYA SRI
- AKSHATHA A REDDY

## Technologies Used
- **Backend**: FastAPI
- **Frontend**: Streamlit
- **Database**: SQLlite
- **Virtualization**: Docker, gVisor
- **CI/CD**: GitHub Actions
- **Other Tools**: Python, Node.js, Git

## Setup Instructions
Follow these steps to set up and run the **Lambda Serverless Function Execution Platform** locally:
### Clone the Repository
```bash
git clone https://github.com/Advaith2805/PES2UG22CS017_PES2UG22CS038_PES2UG22CS045_PES2UG22CS049_LambdaServerlessFunction.git
cd PES2UG22CS017_PES2UG22CS038_PES2UG22CS045_PES2UG22CS049_LambdaServerlessFunction
```
### Start the backend (FastAPI)
```bash
cd backend
uvicorn main:app --reload
```
### Start the frontend (Streamlit)
```bash
cd frontend
streamlit run frontend.py
```
### Tip:
- Run the commands in wsl or a ubuntu machine since gVisor does not run on windows.
- Make sure docker and gVisor is setup and running.
- If the gVisor pool is not being created, add the path of your gVisor installation in the daemon.json file of the docker engine.

## Folder Structure
```bash
PES2UG22CS017_PES2UG22CS038_PES2UG22CS045_PES2UG22CS049/
├─ .github/
├─ backend/
├─ frontend/
├─ docker-exec2/
├─ monitoring/
├─ .env
├─ .gitignore
├─ README.md
├─ structure.png
```
