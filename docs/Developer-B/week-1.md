[ USER IN TERMINAL ]
        │
        ▼
1. verity/cli.py (Task B1.4) 
        │   - Parses the terminal command.
        │   - Calls scan_url() in main.py.
        ▼
2. verity/orchestrator/main.py (Task B1.3)
        │   - The "Manager". 
        │   - Creates an RPCClient to talk to Node.
        ▼
3. verity/orchestrator/rpc_client.py (Task B1.2)
        │   - The "Telephone". 
        │   - Spawns Developer A's Node.js worker in the background.
        │   - Sends {"method": "render"} and {"method": "runAxe"} over stdio.
        ▼
[ NODE.JS WORKER DOES THE BROWSER WORK & REPLIES WITH RAW JSON ]
        │
        ▼
3. verity/orchestrator/rpc_client.py (Task B1.2)
        │   - Hears the JSON reply from Node.js and hands it back up to main.py.
        ▼
2. verity/orchestrator/main.py (Task B1.3)
        │   - Receives raw, messy JSON from Node.js.
        │   - Uses your data models to clean it up.
        ▼
4. verity/models/schemas.py (Task B1.1)
        │   - The "Rulebook". main.py uses these strict Pydantic classes 
        │     to map the raw data into an official `AuditReport` and `Finding`.
        ▼
2. verity/orchestrator/main.py (Task B1.3)
        │   - Returns the beautiful, strict `AuditReport` back to the CLI.
        ▼
1. verity/cli.py (Task B1.4)
        │   - Prints the pretty summary box to the user's screen.
        │   - Saves the report.json file to the hard drive.


1. verity/models/schemas.py (Task B1.1 - The Vocabulary)
Who calls it: main.py and cli.py both import it.

What it does: It doesn't "do" actions; it defines the shape of the data. It ensures that when main.py says "I found a bug," that bug has a strictly enforced severity, provenance, and Evidence. It is the dictionary the rest of your app uses to speak to each other.

2. verity/orchestrator/rpc_client.py (Task B1.2 - The Telephone)
Who calls it: main.py.

What it does: It handles the messy OS-level work. It launches the background Node.js process, sends JSON requests, handles timeouts (so the app doesn't freeze forever if a website is slow), and reads the output. It knows how to talk, but it doesn't care what it is saying.

3. verity/orchestrator/main.py (Task B1.3 - The Manager)
Who calls it: cli.py.

What it does: This is the brain of the operation. It tells rpc_client.py exactly what to say to Node ("render", then "runAxe"). When Node replies with raw axe-core data, main.py uses schemas.py to transform that raw data into an official AuditReport.

4. verity/cli.py (Task B1.4 - The Front Door)
Who calls it: The human user (or a GitHub Actions automated script).

What it does: It takes the human's terminal input, translates it into Python variables, and hands it to main.py. When main.py is done, cli.py draws the ASCII summary box on the screen and decides if the program should exit with a 0 (Success) or 1 (Failure).

Where does Task B1.5 (eval/inject/) fit in?
You might notice the fault injectors (strip_alt.py, detach_label.py, reduce_contrast.py) are not in the flow chart above.

That is because they are not part of the main application. They sit in a "side-car" directory (eval/).

Who calls them: The automated testing scripts (and eventually, the Phase 4 Evaluation Harness).

What they do: They are strictly for testing the main app. Before you run cli.py, a test script will use strip_alt.py to maliciously break a local HTML file. Then, the test script will ask main.py to scan that broken file. Finally, the test script will check if main.py successfully caught the trap!