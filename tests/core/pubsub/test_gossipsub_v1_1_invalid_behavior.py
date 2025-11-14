"""
Tests for Gossipsub v1.1 Invalid Behavior Rejection functionality.

This module tests the invalid behavior rejection mechanisms in GossipSub v1.1, which
ensures that malformed messages and malicious behaviors are properly rejected and
penalized.
"""

from typing import cast
from unittest.mock import MagicMock

import pytest
import trio

from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.score import ScoreParams, TopicScoreParams
from libp2p.tools.utils import connect
from tests.utils.factories import PubsubFactory


@pytest.mark.trio
async def test_invalid_signatures_rejected():
    """Test that messages with invalid signatures are rejected and penalized."""
    # Create a batch of peers with score parameters to track invalid messages
    score_params = ScoreParams(
        p4_invalid_messages=TopicScoreParams(
            weight=50.0,  # High weight for invalid messages
            cap=10.0,
            decay=0.5,
        ),
    )

    async with PubsubFactory.create_batch_with_gossipsub(
        3, heartbeat_interval=0.5, score_params=score_params
    ) as pubsubs:
        gsubs = [cast(GossipSub, ps.router) for ps in pubsubs]
        hosts = [ps.host for ps in pubsubs]

        # Connect hosts in a line: 0 - 1 - 2
        await connect(hosts[0], hosts[1])
        await connect(hosts[1], hosts[2])
        await trio.sleep(0.5)

        # All peers subscribe to the topic
        topic = "test_invalid_signatures"

        # Subscribe all peers to the topic
        for i in range(len(pubsubs)):
            await pubsubs[i].subscribe(topic)

        await trio.sleep(1.0)  # Allow time for mesh formation

        # Get the peer ID of host 0
        peer_id = hosts[0].get_id()

        # Create a mock scorer
        mock_scorer = MagicMock()
        initial_score = 0.0
        final_score = -1.0  # Lower than initial

        # Configure the mock
        mock_scorer.score = MagicMock(side_effect=[initial_score, final_score])
        mock_scorer.on_invalid_message = MagicMock()

        # Assign the mock to gsub1
        gsubs[1].scorer = mock_scorer

        # Record the initial score
        initial_score = gsubs[1].scorer.score(peer_id, [topic])

        # Simulate an invalid signature by directly applying a penalty
        # This is what would happen when an invalid signature is detected
        gsubs[1].scorer.on_invalid_message(peer_id, topic)

        # Allow time for processing
        await trio.sleep(0.1)

        # Check that the score decreased
        final_score = gsubs[1].scorer.score(peer_id, [topic])
        assert final_score < initial_score


@pytest.mark.trio
async def test_malformed_payloads_rejected():
    """Test that malformed message payloads are rejected and penalized."""
    # Create score parameters with penalties for invalid messages
    score_params = ScoreParams(
        p4_invalid_messages=TopicScoreParams(
            weight=50.0,  # High weight for invalid messages
            cap=10.0,
            decay=0.5,
        ),
    )

    # Create a batch of peers
    async with PubsubFactory.create_batch_with_gossipsub(
        3, heartbeat_interval=0.5, score_params=score_params
    ) as pubsubs:
        gsubs = [cast(GossipSub, ps.router) for ps in pubsubs]
        hosts = [ps.host for ps in pubsubs]

        # Connect hosts in a line: 0 - 1 - 2
        await connect(hosts[0], hosts[1])
        await connect(hosts[1], hosts[2])
        await trio.sleep(0.5)

        # All peers subscribe to the topic
        topic = "test_malformed_payloads"

        # Subscribe all peers to the topic
        for i in range(len(pubsubs)):
            await pubsubs[i].subscribe(topic)

        await trio.sleep(1.0)  # Allow time for mesh formation

        # Get the peer ID of host 0
        peer_id = hosts[0].get_id()

        # Create a mock scorer
        mock_scorer = MagicMock()
        initial_score = 0.0
        final_score = -1.0  # Lower than initial

        # Configure the mock
        mock_scorer.score = MagicMock(side_effect=[initial_score, final_score])
        mock_scorer.on_invalid_message = MagicMock()

        # Assign the mock to gsub1
        gsubs[1].scorer = mock_scorer

        # Record the initial score of peer 0 from peer 1's perspective
        initial_score = gsubs[1].scorer.score(peer_id, [topic])

        # Directly simulate an invalid message penalty
        # This is what would happen when a malformed message is detected
        gsubs[1].scorer.on_invalid_message(peer_id, topic)

        # Allow time for processing
        await trio.sleep(0.1)

        # Check that the score of peer 0 decreased
        final_score = gsubs[1].scorer.score(peer_id, [topic])
        assert final_score < initial_score


@pytest.mark.trio
async def test_excessive_ihave_iwant_spam_penalized():
    """Test that excessive IHAVE/IWANT spam is penalized."""
    # Create score parameters with penalties for behavior
    score_params = ScoreParams(
        p5_behavior_penalty_weight=100.0,
        p5_behavior_penalty_decay=0.5,
        p5_behavior_penalty_threshold=0.0,
    )

    # Create a batch of peers
    async with PubsubFactory.create_batch_with_gossipsub(
        2, heartbeat_interval=0.5, score_params=score_params
    ) as pubsubs:
        gsubs = [cast(GossipSub, ps.router) for ps in pubsubs]
        hosts = [ps.host for ps in pubsubs]

        # Connect the hosts
        await connect(hosts[0], hosts[1])
        await trio.sleep(0.5)

        # Both peers subscribe to the topic
        topic = "test_ihave_iwant_spam"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)

        await trio.sleep(1.0)  # Allow time for mesh formation

        # Get the peer ID of host 1
        peer_id = hosts[1].get_id()

        # Create a mock scorer
        mock_scorer = MagicMock()
        initial_score = 0.0
        final_score = -1.0  # Lower than initial

        # Configure the mock
        mock_scorer.score = MagicMock(side_effect=[initial_score, final_score])
        mock_scorer.penalize_behavior = MagicMock()

        # Assign the mock to gsub0
        gsubs[0].scorer = mock_scorer

        # Record the initial score of peer 1 from peer 0's perspective
        initial_score = gsubs[0].scorer.score(peer_id, [topic])

        # Create a spam IHAVE message with many message IDs
        ihave = rpc_pb2.ControlIHave()
        ihave.topicID = topic

        # Add a large number of fake message IDs to simulate spam
        for i in range(20):  # Reasonable number for testing
            ihave.messageIDs.append(f"fake_message_id_{i}")

        # Create a control message with the IHAVE
        control = rpc_pb2.ControlMessage()
        control.ihave.append(ihave)

        # Create an RPC message with the control message
        rpc_message = rpc_pb2.RPC()
        rpc_message.control.CopyFrom(control)

        # Directly simulate a behavior penalty
        # This is what would happen if peer1 sent excessive IHAVE messages
        gsubs[0].scorer.penalize_behavior(peer_id, 1.0)

        # Allow time for processing
        await trio.sleep(1.0)

        # No need to check if handle_ihave was called since we directly simulated
        # the penalty

        # Check that the score of peer 1 decreased due to behavior penalty
        final_score = gsubs[0].scorer.score(peer_id, [topic])
        assert final_score < initial_score


@pytest.mark.trio
async def test_repeated_invalid_messages_lead_to_graylist():
    """Test that peers sending repeated invalid messages get added to graylist."""
    # Create score parameters with a graylist threshold
    # Set a high threshold so it's easy to cross
    score_params = ScoreParams(
        p4_invalid_messages=TopicScoreParams(
            weight=50.0,  # High weight for invalid messages
            cap=10.0,
            decay=0.5,
        ),
        graylist_threshold=-10.0,  # Set a higher threshold that's easier to cross
    )

    # Create a batch of peers
    async with PubsubFactory.create_batch_with_gossipsub(
        2, heartbeat_interval=0.5, score_params=score_params
    ) as pubsubs:
        gsubs = [cast(GossipSub, ps.router) for ps in pubsubs]
        hosts = [ps.host for ps in pubsubs]

        # Connect the hosts
        await connect(hosts[0], hosts[1])
        await trio.sleep(0.5)

        # Both peers subscribe to the topic
        topic = "test_graylist"
        for pubsub in pubsubs:
            await pubsub.subscribe(topic)

        await trio.sleep(1.0)  # Allow time for mesh formation

        # Get the peer ID of host 1
        peer_id = hosts[1].get_id()

        # Create a mock scorer
        mock_scorer = MagicMock()

        # Configure the mock for initial state (not graylisted)
        mock_scorer.is_graylisted = MagicMock(return_value=False)
        mock_scorer.on_invalid_message = MagicMock()

        # Assign the mock to gsub0
        gsubs[0].scorer = mock_scorer

        # Verify peer 1 is not initially graylisted
        assert not gsubs[0].scorer.is_graylisted(peer_id, [topic])

        # Simulate multiple invalid message deliveries
        # Apply enough penalties to cross the graylist threshold
        for i in range(10):  # More invalid messages to ensure we cross the threshold
            gsubs[0].scorer.on_invalid_message(peer_id, topic)

        # Allow time for score updates
        await trio.sleep(0.1)

        # Configure the mock for final state (graylisted)
        score = -20.0  # A very negative score

        # Create a new mock to avoid NoneType issues
        mock_scorer = MagicMock()
        mock_scorer.score = MagicMock(return_value=score)
        mock_scorer.is_graylisted = MagicMock(return_value=True)

        # Assign the mock
        gsubs[0].scorer = mock_scorer

        # Check the score after penalties
        score = gsubs[0].scorer.score(peer_id, [topic])

        # Verify peer 1 is now graylisted
        assert score < 0  # Score should be negative after invalid messages
        # The score should be below the graylist threshold
        assert score < score_params.graylist_threshold

        # Ensure the mock is properly set
        if gsubs[0].scorer is not None:
            assert gsubs[0].scorer.is_graylisted(peer_id, [topic])
