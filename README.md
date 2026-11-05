# Smart Campus Digital Twin

**Interactive Campus Monitoring | Data Processing & Analytics | 2D/3D Visualization**

Academic engineering project developed at **Technische Universität Berlin (TU Berlin)** as part of an international German-Japanese Smart Campus collaboration.

## Project Overview

The Smart Campus Digital Twin is an integrated software platform designed to collect, process, analyze, predict, and visualize campus occupancy and environmental data.

The platform combines sensor measurements, data analytics, interactive 2D/3D visualizations, and communication with a physical campus model.

Its objective is to transform raw measurements into meaningful information through a web-based dashboard, supporting occupancy monitoring, historical analysis, and data-driven decision-making.

The project was developed collaboratively by an international engineering team, combining software development, data processing, and system integration.

## Key Features

- **Interactive 2D Campus Map:** Visualization of campus buildings and occupancy information.
- **3D Campus Visualization:** Interactive digital representation of the campus environment.
- **3D Occupancy Heatmaps:** Spatial visualization of occupancy distribution across campus buildings.
- **Historical Data Visualization:** Analysis and visualization of occupancy measurements and trends over time.
- **Data Processing & Extrapolation:** Processing of sensor measurements and estimation of occupancy patterns using mathematical methods.
- **Multilingual Interface:** Support for English, German, and Japanese.
- **Environmental Monitoring:** Integration of weather and environmental data.
- **Digital-Physical Integration:** Communication between the digital platform and a physical campus prototype through MQTT.
- **Backend Integration:** REST API communication, PostgreSQL data storage, and data exchange between system components.

## Technology Stack

| Category | Technologies |
|---|---|
| Frontend | React, TypeScript, JavaScript, Vite |
| Backend | Python, FastAPI |
| Data Processing | Python, NumPy, Mathematical Extrapolation |
| Database | PostgreSQL, SQLModel |
| Communication | REST API, MQTT |
| Visualization | Interactive 2D/3D Maps, Heatmaps, Charts |
| Development Tools | Git, GitLab CI, ESLint, Prettier, Ruff |

## My Contributions

**Role: Frontend Development, Data Processing & International Team Coordination**

My primary technical contributions focused on frontend engineering, TypeScript development, data processing, and interactive visualization. I also contributed to selected backend-related tasks and participated in the coordination of the international project team.

### Frontend Development — React & TypeScript

- Developed and improved interactive frontend components using **React and TypeScript**.
- Contributed to the implementation and refinement of 2D and 3D campus visualizations.
- Worked on interactive occupancy heatmaps and historical data visualization.
- Improved dashboard usability, component organization, and user interaction.
- Contributed to multilingual interface functionality supporting German, English, and Japanese.
- Integrated processed occupancy data into interactive dashboard components.

### Data Processing & Analytics

- Contributed substantially to the processing and analysis of campus occupancy data.
- Worked on data preparation, mathematical extrapolation, and visualization workflows.
- Supported the representation of historical occupancy patterns and estimated occupancy values.
- Collaborated on connecting data processing results with frontend visualizations.

### Backend & System Integration

- Made smaller contributions to backend-related development tasks.
- Worked with frontend-backend communication and API integration.
- Gained practical experience with a software architecture using Python, FastAPI, PostgreSQL, and MQTT.

### International Team Coordination

- Coordinated development activities within a German-Japanese engineering project.
- Supported technical communication and collaboration between project participants.
- Participated in project planning, task coordination, and technical presentations.
- Helped align frontend development, data processing, and overall system requirements.

**Contribution Transparency:** This was a collaborative engineering project. My main technical responsibilities were frontend development and data processing, with limited backend involvement. Other system components were developed collaboratively by the project team.

## System Architecture

The platform consists of four main layers.

### 1. Data Acquisition

Sensor measurements and environmental information are collected from the campus environment.

### 2. Backend & Database

FastAPI services handle data exchange, database access, API responses, and communication with external systems.

PostgreSQL and SQLModel provide structured data storage and database interaction.

### 3. Data Processing & Analytics

Python-based processing prepares sensor measurements for analysis, extrapolation, and visualization.

Historical occupancy measurements and estimated values are transformed into data representations suitable for the dashboard.

### 4. Interactive Frontend

A React and TypeScript dashboard presents processed information through interactive campus maps, 3D visualizations, occupancy heatmaps, and historical charts.

The frontend communicates with the backend through REST APIs.

## Project Structure

```text
smart-campus/
├── backend/
│   ├── app/               # FastAPI application
│   ├── pyproject.toml     # Backend dependencies
│   └── README.md          # Backend documentation
│
├── frontend/
│   ├── public/            # Static assets
│   ├── src/               # React and TypeScript source code
│   ├── package.json       # Frontend dependencies
│   └── vite.config.ts     # Vite configuration
│
├── data_processing/       # Data processing and analytics
├── docs/                  # Technical documentation
└── README.md              # Project overview
```

## Software Quality & Development Practices

The project uses development tools and automated checks to support code quality and maintainability.

- **TypeScript:** Static type checking for frontend development.
- **ESLint:** Frontend code quality checks.
- **Prettier:** Consistent code formatting.
- **Ruff:** Python linting and formatting.
- **GitLab CI:** Automated build and quality verification.
- **Git:** Version control and collaborative development.

## Engineering Skills Demonstrated

- React and TypeScript development
- Interactive 2D/3D visualization
- Data processing and mathematical analysis
- Technical dashboard development
- Frontend-backend integration
- REST API communication
- Software architecture and modular development
- Technical problem-solving
- Collaborative software engineering
- International team coordination

## Live Demonstration & Access

The fully deployed Smart Campus platform is hosted within the university infrastructure and requires access to the TU Berlin network.

While the source code and technical documentation are available in this repository, accessing the deployed system requires an authorized university network connection.

**I would be happy to personally demonstrate the final version of the project, walk through its key features, and discuss my technical contributions in more detail during an interview or an in-person meeting.**

## Project Information

**Institution:** Technische Universität Berlin (TU Berlin)  
**Project:** German-Japanese Smart Campus Collaboration  
**Year:** 2026  
**Project Type:** Academic Engineering Project  
**My Role:** Frontend Development, Data Processing, Minor Backend Contributions & International Team Coordination

---

*This repository showcases a collaborative academic engineering project, with particular emphasis on my individual contributions to frontend engineering, data processing, interactive visualization, and international teamwork.*