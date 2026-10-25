This expresses the class model relation between all the main concepts.

contract <1-1> name
contract <*-1> version
contract <1-*> statement
publisher <1-1> contract

statement <1-1> trigger (endpoint)
statement <1-1> expected state
statement <1-1> payload

statement <1-*> verifier

verifier <1-1> name
verifier <1-1> version
verifier <1-1> active
verifier <1-*> test

company <1-*> contract
company <1-*> user
user <1-1> name
user <1-1> email

Invariants:

Whenever statements are added to a contract or removed a new version is generated. 
The version is a number. 
contract and version are unique, this means no two contracts can exist with the same name and version. 
