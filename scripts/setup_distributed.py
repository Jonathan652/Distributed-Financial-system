#!/usr/bin/env python3
"""
Interactive setup helper for multi-machine distributed testing.
Generates commands for each machine role (coordinator, regional node, client).
"""

import json
import sys


def print_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def ask(prompt: str, default: str = "") -> str:
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result if result else default
    return input(f"{prompt}: ").strip()


def main() -> None:
    print_header("Mobile Money Distributed System Setup Helper")

    print("\nThis script will help you configure multi-machine deployment.")
    print("You'll need 5 machines minimum:")
    print("  1. Coordinator")
    print("  2. Regional node - Kampala")
    print("  3. Regional node - Mbarara")
    print("  4. Regional node - Gulu")
    print("  5. Regional node - Jinja")
    print("  6+ Client machines (optional)")

    print_header("Step 1: Coordinator Machine")
    coordinator_ip = ask("Enter coordinator machine IP address")
    coordinator_port = ask("Enter coordinator port", "8081")
    coordinator_db = ask("Enter database path", "/tmp/uganda-ledger.sqlite3")

    print_header("Step 2: Regional Nodes")
    kampala_ip = ask("Enter Kampala node IP")
    mbarara_ip = ask("Enter Mbarara node IP")
    gulu_ip = ask("Enter Gulu node IP")
    jinja_ip = ask("Enter Jinja node IP")
    regional_port = ask("Enter port for all regional nodes", "8082")

    print_header("Step 3: Project Path")
    project_path = ask("Enter path to Mobile-money project", "/path/to/Mobile-money")

    config = {
        "coordinator": {
            "ip": coordinator_ip,
            "port": int(coordinator_port),
            "db": coordinator_db,
        },
        "regional_nodes": {
            "kampala": {"ip": kampala_ip, "port": int(regional_port)},
            "mbarara": {"ip": mbarara_ip, "port": int(regional_port)},
            "gulu": {"ip": gulu_ip, "port": int(regional_port)},
            "jinja": {"ip": jinja_ip, "port": int(regional_port)},
        },
        "project_path": project_path,
    }

    print_header("Generated Configuration")
    print(json.dumps(config, indent=2))

    print_header("Commands for Each Machine")

    print("\n🟦 MACHINE 1: Coordinator")
    print(f"Run this on {coordinator_ip}:")
    print(f"""
cd {project_path}
PYTHONPATH=src python3 -m mobile_money.main \\
  --mode coordinator \\
  --host 0.0.0.0 \\
  --port {coordinator_port} \\
  --db {coordinator_db} \\
  --regions kampala,mbarara,gulu,jinja
""")

    print("\n🟩 MACHINE 2: Kampala Regional Node")
    print(f"Run this on {kampala_ip}:")
    print(f"""
cd {project_path}
PYTHONPATH=src python3 -m mobile_money.main \\
  --mode regional \\
  --region kampala \\
  --host 0.0.0.0 \\
  --port {regional_port} \\
  --coordinator http://{coordinator_ip}:{coordinator_port}
""")

    print("\n🟪 MACHINE 3: Mbarara Regional Node")
    print(f"Run this on {mbarara_ip}:")
    print(f"""
cd {project_path}
PYTHONPATH=src python3 -m mobile_money.main \\
  --mode regional \\
  --region mbarara \\
  --host 0.0.0.0 \\
  --port {regional_port} \\
  --coordinator http://{coordinator_ip}:{coordinator_port}
""")

    print("\n🟧 MACHINE 4: Gulu Regional Node")
    print(f"Run this on {gulu_ip}:")
    print(f"""
cd {project_path}
PYTHONPATH=src python3 -m mobile_money.main \\
  --mode regional \\
  --region gulu \\
  --host 0.0.0.0 \\
  --port {regional_port} \\
  --coordinator http://{coordinator_ip}:{coordinator_port}
""")

    print("\n🟨 MACHINE 5: Jinja Regional Node")
    print(f"Run this on {jinja_ip}:")
    print(f"""
cd {project_path}
PYTHONPATH=src python3 -m mobile_money.main \\
  --mode regional \\
  --region jinja \\
  --host 0.0.0.0 \\
  --port {regional_port} \\
  --coordinator http://{coordinator_ip}:{coordinator_port}
""")

    print_header("Verification Commands")
    print("\n✓ Check coordinator health:")
    print(f"  curl -s http://{coordinator_ip}:{coordinator_port}/health | python3 -m json.tool")

    print("\n✓ Check all regional nodes:")
    print(f"""
for region in kampala mbarara gulu jinja; do
  ip=$(python3 -c "import json; print(json.loads('{json.dumps(config['regional_nodes'])}')['$region']['ip'])")
  echo "\\n$region:"
  curl -s http://$ip:{regional_port}/health | python3 -m json.tool
done
""")

    print("\n✓ Run interactive client (from any machine):")
    print(f"  PYTHONPATH=src python3 scripts/simulate_clients.py --interactive --base-url http://{kampala_ip}:{regional_port}")

    print("\n✓ Run load test (from any machine):")
    print(f"""
PYTHONPATH=src python3 scripts/simulate_clients.py \\
  --clients 40 \\
  --ops 20 \\
  --node-urls http://{kampala_ip}:{regional_port},http://{mbarara_ip}:{regional_port},http://{gulu_ip}:{regional_port},http://{jinja_ip}:{regional_port}
""")

    print_header("Configuration Saved")
    config_file = "distributed_config.json"
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Configuration saved to: {config_file}")

    print("\nNext steps:")
    print("1. Copy the commands above to each machine")
    print("2. Start coordinator first (it will listen on all interfaces)")
    print("3. Start regional nodes (they will connect to coordinator)")
    print("4. From a client machine, run the verification and test commands")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
        sys.exit(1)
