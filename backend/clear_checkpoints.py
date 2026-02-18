import os
import sys

# Ensure backend directory is in path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from supabase_client import get_supabase

def clear_checkpoints():
    print("Initializing Supabase client...")
    client = get_supabase()
    
    # Deleting child tables first to avoid FK constraints if any (though usually cascade)
    tables_to_clear = [
        "checkpoint_writes", 
        "checkpoint_blobs", 
        "checkpoints"
    ]
    
    print("Clearing LangGraph checkpoint tables...")
    for table in tables_to_clear:
        try:
            print(f"  Truncating {table}...")
            # Using thread_id != '0' UUID to match all rows
            # This is a safe way to delete all rows through the PostgREST API
            result = client.table(table).delete().neq("thread_id", "00000000-0000-0000-0000-000000000000").execute()
            count = len(result.data) if result.data else 0
            print(f"  ✅ Cleared {count} rows from {table}")
        except Exception as e:
            print(f"  ⚠️ Error clearing {table}: {e}")

if __name__ == "__main__":
    clear_checkpoints()
