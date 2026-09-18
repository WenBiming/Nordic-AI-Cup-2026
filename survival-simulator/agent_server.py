from fastapi import FastAPI, Body
from src.utils.DTOs import StepResponse
from policies.camper import CamperPolicy

HOST = "0.0.0.0"
PORT = 9052

app = FastAPI(title="Survival Simulator Agent Endpoint")

# One hivemind per server process; it resets its memory when sim_time goes backwards
# (a new game), so it survives the evaluation's three consecutive runs.
# Best known configuration so far: docs/journal.md, Exp 4c (mean 1060 over seeds 0-9).
policy = CamperPolicy(hungry_energy=350, lookback=True, crowd_max=2, scan_period=5)

@app.post("/predict")
def predict(step: StepResponse = Body(...)):
    """
    Receives the current simulation state and returns actions for all agents.
    """
    actions = policy.act(step.model_dump())

    # Must return {"actions": [...]} format
    return {"actions": actions}

@app.get("/")
def index():
    return {"message": "Agent endpoint running!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
