import trio

from .malicious_peer import MaliciousPeer


class AttackNetworkBuilder:
    """Builds test networks with configurable attack scenarios"""

    async def create_eclipse_test_network(
        self,
        honest_nodes: int = 10,
        malicious_nodes: int = 3,
        attack_intensity: float = 0.5,
    ) -> tuple[list[str], list[MaliciousPeer]]:
        honest = [f"honest_{i}" for i in range(honest_nodes)]
        malicious = [
            MaliciousPeer(f"mal_{i}", "eclipse", attack_intensity)
            for i in range(malicious_nodes)
        ]
        await trio.sleep(0.1)
        return honest, malicious

    async def setup_attack_scenario(self, scenario_config: dict) -> list[MaliciousPeer]:
        honest, malicious = await self.create_eclipse_test_network(
            scenario_config.get("honest_nodes", 10),
            scenario_config.get("malicious_nodes", 3),
        )
        return malicious
