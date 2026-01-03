"""
Full graph integration test to verify end-to-end routing.

This test runs the complete LangGraph workflow and verifies that
simple STEM problems route to teaching_architect_node, not clarification_node.
"""

import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(__file__))

from graph import get_graph


async def test_full_workflow():
    """Test complete graph execution for '2x+5=13'."""
    print("\n🔬 Full Graph Integration Test")
    print("=" * 50)
    print("Input: '2x+5=13'")
    print("Expected: Route to teaching_architect → NOT clarification")
    print("=" * 50)
    
    try:
        graph = await get_graph()
        
        initial_state = {
            "input_type": "text",
            "input_content": "2x+5=13",
            "user_id": "test_user",
            "thread_id": "test_workflow_integration",
            "confidence_score": 0.0,
            "detected_ambiguity": False,
            "candidate_topics": [],
            "topic": None,
            "teaching_plan": None,
            "worked_example": None,
            "practice_problem": None,
            "video_url": None,
            "final_response_html": None,
            "requires_user_action": False
        }
        
        config = {"configurable": {"thread_id": "test_workflow_integration"}}
        
        print("\n📡 Streaming graph events...\n")
        
        events = []
        node_sequence = []
        
        async for event in graph.astream(initial_state, config):
            events.append(event)
            node_name = list(event.keys())[0]
            node_sequence.append(node_name)
            
            node_state = event[node_name]
            
            print(f"🔹 Node: {node_name}")
            if "confidence_score" in node_state:
                print(f"   Confidence: {node_state['confidence_score']:.2f}")
            if "topic" in node_state and node_state["topic"]:
                print(f"   Topic: {node_state['topic']}")
            print()
        
        # Get final state
        final_event = events[-1]
        final_state = list(final_event.values())[0]
        
        print("\n📊 Final Results:")
        print(f"   Node Sequence: {' → '.join(node_sequence)}")
        print(f"   Final Confidence: {final_state.get('confidence_score', 0):.2f}")
        print(f"   Final Topic: {final_state.get('topic', 'None')}")
        print(f"   Requires User Action: {final_state.get('requires_user_action', False)}")
        print(f"   Has Teaching Plan: {'teaching_plan' in final_state and final_state['teaching_plan'] is not None}")
        
        # Assertions
        assert final_state.get("confidence_score", 0) >= 0.9, \
            f"❌ Confidence should be high (>= 0.9), got {final_state.get('confidence_score', 0)}"
        
        assert "clarification" not in node_sequence, \
            f"❌ Should NOT route to clarification node! Sequence: {node_sequence}"
        
        assert "teaching_architect" in node_sequence, \
            f"❌ Should route to teaching_architect! Sequence: {node_sequence}"
        
        assert final_state.get("requires_user_action") == False, \
            "❌ Should not require user clarification for simple equation"
        
        print("\n✅ Full Workflow Test PASSED!")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(test_full_workflow())
