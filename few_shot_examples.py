examples = [
    {
        "input": "'My father, Jorge Guillermo Borges, worked as a lawyer. He was a philosophical anarchist - a disciple of Spencer - and also a teacher of psychology at the Normal School for Modern Languages, where he gave his course in English, using as his text William James’s shorter book of psychology.'",
        "output": """[
            {
                "entity": {
                    "name": "Jorge Guillermo Borges",
                    "type": "Person",
                    "category": "Family members",
                    "description": "Borges’s father, a lawyer and teacher",
                    "references": [
                        {
                            "text": "My father, Jorge Guillermo Borges, worked as a lawyer. He was a philosophical anarchist - a disciple of Spencer - and also a teacher of psychology",
                            "category": "biographical",
                            "source": "Autobiographical notes",
                            "location": "paragraph 2"
                        }
                    ],
                    "indirect_references": null
                },
                "relationships": [
                    {"type": "INFLUENCES", "target": "Borges", "source": "Autobiographical notes", "location": "paragraph 2"}
                ]
            },
            {
                "entity": {
                    "name": "Spencer, Herbert",
                    "type": "Person",
                    "category": "Historical figures",
                    "description": "English philosopher admired by Borges’s father",
                    "references": [
                        {
                            "text": "Borges mentions that his father was a disciple of Spencer",
                            "category": "influence",
                            "source": "Autobiographical notes",
                            "location": "paragraph 2"
                        }
                    ],
                    "indirect_references": null
                },
                "relationships": [
                    {"type": "INFLUENCES", "target": "Jorge Guillermo Borges", "source": "Autobiographical notes", "location": "paragraph 2"}
                ]
            },
            {
                "entity": {
                    "name": "Psychology: Briefer Course",
                    "type": "Other Literary/Artistic Works",
                    "category": "Books",
                    "description": "William James's book used by Borges's father",
                    "references": [
                        {
                            "text": "The book Borges's father used to teach psychology at the Normal School of Modern Languages",
                            "category": "biographical",
                            "source": "Autobiographical notes",
                            "location": "paragraph 2"
                        }
                    ],
                    "indirect_references": ["James, William"]
                },
                "relationships": [
                    {"type": "WROTE", "target": "James, William", "source": "Autobiographical notes", "location": "paragraph 2"}
                ]
            }
        ]"""
    },
    {
        "input": "'It was also in Geneva that I first met Walt Whitman, through a German translation by Johannes Schlaf (\"Als ich in Alabama meinen Morgengang machte\"). I ordered a copy of \"Leaves of Grass\" from London.'",
        "output": """[
            {
                "entity": {
                    "name": "Geneva",
                    "type": "Place",
                    "category": "Cities",
                    "description": "City where Borges lived and discovered Whitman",
                    "references": [
                        {
                            "text": "It was also in Geneva that I first met Walt Whitman",
                            "category": "biographical",
                            "source": "Autobiographical notes",
                            "location": "paragraph 22"
                        }
                    ],
                    "indirect_references": ["Switzerland"]
                },
                "relationships": [
                    {"type": "LOCATED_IN", "target": "Switzerland", "source": "Autobiographical notes", "location": "paragraph 22"}
                ]
            },
            {
                "entity": {
                    "name": "Whitman, Walt",
                    "type": "Person",
                    "category": "Writers/Authors",
                    "description": "American poet admired by Borges",
                    "references": [
                        {
                            "text": "I first met Walt Whitman, through a German translation by Johannes Schlaf",
                            "category": "criticism",
                            "source": "Autobiographical notes",
                            "location": "paragraph 22"
                        }
                    ],
                    "indirect_references": ["Romanticism"]
                },
                "relationships": [
                    {"type": "WROTE", "target": "Leaves of Grass", "source": "Autobiographical notes", "location": "paragraph 22"},
                    {"type": "INFLUENCED_BY", "target": "Romanticism", "source": "Autobiographical notes", "location": "paragraph 22"}
                ]
            },
            {
                "entity": {
                    "name": "Leaves of Grass",
                    "type": "Other Literary/Artistic Works",
                    "category": "Poems",
                    "description": "Walt Whitman's poem, ordered by Borges",
                    "references": [
                        {
                            "text": "I ordered a copy of \"Leaves of Grass\" from London",
                            "category": "biographical",
                            "source": "Autobiographical notes",
                            "location": "paragraph 22"
                        }
                    ],
                    "indirect_references": ["Whitman, Walt"]
                },
                "relationships": [
                    {"type": "WROTE", "target": "Whitman, Walt", "source": "Autobiographical notes", "location": "paragraph 22"}
                ]
            }
        ]"""
    }
]
