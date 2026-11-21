"""CLI entry point for model training."""
from dengue_watch.pipeline import run_pipeline
import argparse

def main():
    parser = argparse.ArgumentParser(description="Train dengue forecasting models")
    parser.add_argument("--data", default="data/bangladesh_dengue_large_dataset.csv")
    parser.add_argument("--output", default="artifacts")
    args = parser.parse_args()
    run_pipeline(args.data, args.output)

if __name__ == "__main__":
    main()
