# Serving and submitting

## Choose the policy

Named configurations live in `policies/presets.py` (one per experiment worth serving; scores are 10-seed
means from `docs/journal.md`). List them:

```
python agent_server.py --list
```

Start the endpoint with a preset, a preset plus overrides, or any policy class with explicit kwargs:

```
python agent_server.py                                   # default preset (DEFAULT_PRESET in presets.py)
python agent_server.py --preset 13a
python agent_server.py --preset 14a --kw pop_cap=10      # kwargs are KEY=JSON and override the preset's
python agent_server.py --policy policies.camper2:Camper2Policy --kw sprint_zone=130 aware=true select=true
python agent_server.py --preset 14a --host 0.0.0.0 --port 9052
```

`GET /` returns the loaded preset, class and kwargs — check it before starting a platform attempt.

The same names work in experiments: `python -m experiments.run --name x --policy <spec> --kw ...` takes
the spec and kwargs printed by `--list`.

## Submit

1. `source .venv/bin/activate && python agent_server.py --preset <name>`; `GET /` must answer.
2. In a second terminal `python simulation_server.py` plays a full game (seed 1) over HTTP against the
   endpoint, as the platform does. It must reach `Game finished!` with no `Error contacting agent`.
3. Make port 9052 reachable from the platform (VPS, or a tunnel such as `ngrok http 9052`) and register the
   public URL where the platform asks for the agent endpoint (it POSTs to `/predict`).
4. Run a *validation* attempt first (unlimited, random seeds). Only then the single *evaluation* attempt:
   three consecutive games averaged. Keep the same server process running throughout — the hivemind resets
   its memory whenever `sim_time` goes backwards, so one process serves all three games.

Constraints: 10 s per request, 600 s accumulated per run ⇒ ~20 ms per tick including the network. The
policies use 0.3–0.6 ms; a tunnel with < 15 ms round-trip is fine, a distant relay is not. The machine must
not sleep during the attempt.
