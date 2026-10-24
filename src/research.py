import re
import argparse
from pathlib import Path
from .deep_research import InteractiveDeepResearch

def create_safe_filename(topic: str) -> str:
    """Convert research topic to safe filename format"""
    filename = topic.lower()
    filename = re.sub(r'[^\w\s-]', '_', filename)
    filename = re.sub(r'[\s_]+', '_', filename)
    filename = filename.strip('_')
    return filename

def get_versioned_filepath(topic: str, output_dir: str = "results") -> str:
    """Generate versioned filepath for research results"""
    results_dir = Path(output_dir)
    results_dir.mkdir(exist_ok=True)
    
    base_filename = create_safe_filename(topic)
    filepath = results_dir / f"{base_filename}.md"
    
    counter = 2
    while filepath.exists():
        filepath = results_dir / f"{base_filename}_{counter}.md"
        counter += 1
    
    return str(filepath)

def main():
    parser = argparse.ArgumentParser(
        description="AI-powered deep research tool that generates comprehensive reports on any topic",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.research "Climate change effects on agriculture"
  python -m src.research "AI in healthcare" -o reports --max-queries 6 --max-search 3
  python -m src.research "Renewable energy trends" --max-iteration 5 --max-tokens 16384
        """
    )
    
    parser.add_argument("topic", 
                       help="Research topic to investigate (use quotes for multi-word topics)")
    
    parser.add_argument("--output-dir", "-o", 
                       default="results", 
                       metavar="DIR",
                       help="Directory to save research results (default: %(default)s)")
    
    parser.add_argument("--max-queries", 
                       type=int, 
                       metavar="N",
                       help="Search queries per iteration (default: config.yaml)")
    
    parser.add_argument("--max-iteration", 
                       type=int, 
                       metavar="N",
                       help="Research iterations (default: config.yaml)")
    
    parser.add_argument("--max-tokens", 
                       type=int, 
                       metavar="N",
                       help="Maximum completion tokens per model call (default: config.yaml)")

    parser.add_argument("--max-search", 
                       type=int, 
                       metavar="N",
                       help="Search results per query (default: config.yaml)")

    parser.add_argument("--thres", 
                       type=float, 
                       metavar="X",
                       help="Minimum rerank score (0-1) to keep a source (default: config.yaml)")
    
    args = parser.parse_args()
    
    # Unset flags fall back to config/config.yaml
    researcher = InteractiveDeepResearch(
        max_queries=args.max_queries,
        max_searchs=args.max_search,
        max_iteration=args.max_iteration,
        max_completion_token=args.max_tokens,
        rerank_score_threshold=args.thres
    )
    
    print(f"Starting research on: {args.topic}")
    result = researcher(args.topic)
    
    output_file = get_versioned_filepath(args.topic, args.output_dir)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(result)
    
    print(f"Research completed and saved to: {output_file}")

if __name__ == "__main__":
    main()
