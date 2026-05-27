"""Alpha Bot entry point. Full bot loop comes in Phase 4."""
from loguru import logger

from config import settings


def main() -> None:
    logger.info("Alpha Bot — Phase 1 scaffold. Run scripts/test_phase1.py for the signal demo.")
    logger.info("Mode: {} | Testnet: {}", "PAPER" if settings.paper_trading else "LIVE", settings.binance_testnet)


if __name__ == "__main__":
    main()
