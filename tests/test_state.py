"""Tests for the state machine."""

import json
import pytest
from pathlib import Path

from trainer.state import AgentState, CycleScore, InvalidTransition, State, StateMachine


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path / "state"


@pytest.fixture
def sm(state_dir):
    return StateMachine(state_dir)


class TestStateMachine:
    def test_initial_state_is_idle(self, sm):
        assert sm.status == State.IDLE

    def test_valid_transition(self, sm):
        sm.transition(State.FETCHING_WALKTHROUGH)
        assert sm.status == State.FETCHING_WALKTHROUGH

    def test_invalid_transition_raises(self, sm):
        with pytest.raises(InvalidTransition):
            sm.transition(State.COMMITTING)

    def test_state_persists_to_disk(self, state_dir, sm):
        sm.transition(State.FETCHING_WALKTHROUGH)
        # Load a new state machine from the same directory
        sm2 = StateMachine(state_dir)
        assert sm2.status == State.FETCHING_WALKTHROUGH

    def test_init_cycle(self, sm):
        sm.init_cycle("testcase", 1)
        assert sm.current.case_name == "testcase"
        assert sm.current.cycle == 1
        assert sm.current.iteration == 0

    def test_increment_iteration(self, sm):
        sm.init_cycle("testcase", 1)
        sm.increment_iteration()
        assert sm.current.iteration == 1

    def test_record_score(self, sm):
        sm.init_cycle("testcase", 1)
        score = CycleScore(iteration=0, score_numeric=85.5, score_display="85.5%")
        sm.record_score(score)
        assert len(sm.current.scores) == 1
        assert sm.current.scores[0]["score_numeric"] == 85.5

    def test_record_cost(self, sm):
        sm.init_cycle("testcase", 1)
        sm.record_cost(2.50)
        sm.record_cost(1.25)
        assert sm.current.cost_usd == pytest.approx(3.75)

    def test_set_error_transitions_to_failed(self, sm):
        sm.set_error("something broke")
        assert sm.status == State.FAILED
        assert sm.current.last_error == "something broke"

    def test_reset_clears_error(self, sm):
        sm.set_error("broken")
        sm.reset()
        assert sm.status == State.IDLE
        assert sm.current.last_error == ""

    def test_can_resume_false_when_idle(self, sm):
        assert not sm.can_resume()

    def test_can_resume_true_when_active(self, sm):
        sm.init_cycle("testcase", 1)
        sm.transition(State.FETCHING_WALKTHROUGH)
        assert sm.can_resume()

    def test_full_cycle_transitions(self, sm):
        """Walk through a complete successful cycle."""
        sm.transition(State.FETCHING_WALKTHROUGH)
        sm.transition(State.BUILDING_ANSWER_KEY)
        sm.transition(State.ANALYZING_GAPS)
        sm.transition(State.IMPLEMENTING_FIXES)
        sm.transition(State.RUNNING_EXTRACTION)
        sm.transition(State.RUNNING_FULL_PIPELINE)
        sm.transition(State.COMPARING_RESULTS)
        sm.transition(State.RUNNING_REGRESSION)
        sm.transition(State.AWAITING_APPROVAL)
        sm.transition(State.COMMITTING)
        sm.transition(State.IDLE)
        assert sm.status == State.IDLE

    def test_corrupt_state_file_recovers(self, state_dir):
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "agent_state.json").write_text("not json{{{")
        sm = StateMachine(state_dir)
        assert sm.status == State.IDLE
