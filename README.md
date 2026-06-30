# API Performance Monitor

A containerized, multi-tenant uptime tracking dashboard. 

I built this project to solve a specific problem: how to run continuous background polling (pinging dozens of URLs every minute) without blocking concurrent incoming API requests from users. The solution leverages Python's `asyncio` for non-blocking background workers, paired with a React/Next.js frontend for real-time visualization.

Tech Stack

- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS
- **Backend:** Python, FastAPI, Motor (Async MongoDB Driver), Passlib (Argon2 for hashing)
- **Database:** MongoDB
- **Infrastructure:** Docker, Docker Compose

Core Features

- **Asynchronous Polling Engine:** Uses `asyncio.gather()` to concurrently ping tracked endpoints. The background worker yields to the event loop, ensuring the main FastAPI server remains highly responsive.
- **Multi-Tenant Isolation:** Secured via JWT authentication. Users can only read, write, and view tracking data associated with their specific `user_id`. 
- **Real-time Client Polling:** The Next.js dashboard securely fetches new logs every 10 seconds, updating the UI dynamically without page reloads.
- **Graceful Error Handling:** Captures and logs timeouts, 500s, and connection errors without crashing the background worker.

Local Setup & Execution

The entire architecture (frontend, backend, database) is containerized. You do not need Python or Node.js installed locally to run this project—only Docker.

Prerequisites
- Docker & Docker Compose installed on your machine.

1. Clone the repository
`git clone https://github.com/cezium55/api-performance-monitor.git`
`cd api-performance-monitor`

2. Environment Variables
Create a `.env` file in the `backend/` directory to store your secrets. You can copy the structure below:

`MONGODB_URI=mongodb://db:27017`
`MONGODB_DB=monitor_db`
`SECRET_KEY=your_super_secret_jwt_key_here`
`ALGORITHM=HS256`
`ACCESS_TOKEN_EXPIRE_MINUTES=30`

3. Spin up the containers
Execute the following command from the root directory:
`docker-compose up --build`

4. Access the Application
- **Frontend UI:** http://localhost:3000
- **Backend API Docs:** http://localhost:8000/docs

Architecture Notes
**Why MongoDB?** Uptime monitoring generates massive amounts of time-series log data quickly. A NoSQL document store allows for rapid, schema-less inserts for ping results, which scales better for this specific write-heavy workload compared to a traditional relational database.

Roadmap / Future Enhancements
- [ ] **CI/CD Pipeline:** Implement GitHub Actions to automate testing and deployment to an AWS EC2 instance.
- [ ] **Alerting System:** Integrate SendGrid/Resend to email users immediately when an endpoint returns a status code outside the 200-299 range.
