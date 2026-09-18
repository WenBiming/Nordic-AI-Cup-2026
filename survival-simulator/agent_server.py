from fastapi import FastAPI, Body
from src.utils.DTOs import StepResponse
from policies.camper2 import Camper2Policy

HOST = "0.0.0.0"
PORT = 9052

app = FastAPI(title="Survival Simulator Agent Endpoint")

# One hivemind per server process; it resets its memory when sim_time goes backwards
# (a new game), so it survives the evaluation's three consecutive runs.
# Best known configuration so far: docs/journal.md, Exp 13a (mean 1111, min 867 over seeds 0-9).
policy = Camper2Policy(sprint_zone=130, aware=True, select=True, old_always=True)

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
