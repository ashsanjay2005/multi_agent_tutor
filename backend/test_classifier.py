"""
Test script for granular topic classification and step-by-step solutions.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from graph import text_classifier_node, step_solver_node
from state import GraphState


async def test_cross_product():
    """Test that '[9 8 3] x [2 1 4]' is classified as Cross Product."""
    print("\n🔬 Test 1: Cross Product Classification")
    print("=" * 50)
    
    state = {
        "input_type": "text",
        "input_content": "[9 8 3] x [2 1 4]",
        "user_id": "test_user",
        "thread_id": "test_thread",
        "confidence_score": 0.0,
        "detected_ambiguity": False,
        "candidate_topics": [],
        "topic": None,
        "teaching_plan": None,
        "worked_example": None,
        "practice_problem": None,
        "video_url": None,
        "solution_steps": None,
        "final_response_html": None,
        "requires_user_action": False
    }
    
    result = await text_classifier_node(state)
    
    print(f"\n📊 Results:")
    print(f"   Topic: {result['topic']}")
    print(f"   Confidence: {result['confidence_score']}")
    
    assert result["confidence_score"] >= 0.9, f"❌ Expected high confidence, got {result['confidence_score']}"
    assert "Cross Product" in result["topic"], f"❌ Expected 'Cross Product' in topic, got {result['topic']}"
    
    print(f"\n✅ Test 1 PASSED - Correctly identified as Cross Product!")
    return result


async def test_matrix_multiplication():
    """Test matrix multiplication classification."""
    print("\n🔬 Test 2: Matrix Multiplication Classification")
    print("=" * 50)
    
    state = {
        "input_type": "text",
        "input_content": "multiply [[1,2],[3,4]] and [[5,6],[7,8]]",
        "user_id": "test_user",
        "thread_id": "test_thread",
        "confidence_score": 0.0,
        "detected_ambiguity": False,
        "candidate_topics": [],
        "topic": None,
        "teaching_plan": None,
        "worked_example": None,
        "practice_problem": None,
        "video_url": None,
        "solution_steps": None,
        "final_response_html": None,
        "requires_user_action": False
    }
    
    result = await text_classifier_node(state)
    
    print(f"\n📊 Results:")
    print(f"   Topic: {result['topic']}")
    print(f"   Confidence: {result['confidence_score']}")
    
    assert result["confidence_score"] >= 0.9, f"❌ Expected high confidence, got {result['confidence_score']}"
    assert "Matrix" in result["topic"], f"❌ Expected 'Matrix' in topic, got {result['topic']}"
    
    print(f"\n✅ Test 2 PASSED!")
    return result


async def test_step_solver():
    """Test that step_solver generates steps."""
    print("\n🔬 Test 3: Step-by-Step Solution Generation")
    print("=" * 50)
    
    state = {
        "input_type": "text",
        "input_content": "[9 8 3] x [2 1 4]",
        "user_id": "test_user",
        "thread_id": "test_thread",
        "topic": "Math - Linear Algebra - Cross Product",
        "confidence_score": 1.0,
        "detected_ambiguity": False,
        "candidate_topics": [],
        "teaching_plan": None,
        "worked_example": None,
        "practice_problem": None,
        "video_url": None,
        "solution_steps": None,
        "final_response_html": None,
        "requires_user_action": False
    }
    
    result = await step_solver_node(state)
    
    print(f"\n📊 Results:")
    print(f"   Number of steps: {len(result['solution_steps'])}")
    print(f"   Final answer: {result['worked_example'][:100]}...")
    
    for step in result['solution_steps']:
        print(f"\n   Step {step['step_number']}: {step['title']}")
        print(f"      {step['explanation'][:80]}...")
    
    assert len(result['solution_steps']) >= 3, f"❌ Expected at least 3 steps, got {len(result['solution_steps'])}"
    assert result['worked_example'] is not None, "❌ Expected final answer"
    
    print(f"\n✅ Test 3 PASSED - Generated {len(result['solution_steps'])} steps!")
    return result


async def main():
    print("\n" + "=" * 50)
    print("🧪 GRANULAR CLASSIFICATION & STEP SOLVER TESTS")
    print("=" * 50)
    
    try:
        await test_cross_product()
        await test_matrix_multiplication()
        await test_step_solver()
        
        print("\n" + "=" * 50)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 50)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
