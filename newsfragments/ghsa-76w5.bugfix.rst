Circuit Relay v2 RESERVE now keys reservation admission on the authenticated
connection peer and rejects ``msg.peer`` values that do not match, so a
connected peer cannot consume reservation slots under unrelated peer IDs.
