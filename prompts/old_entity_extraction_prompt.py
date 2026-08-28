OLD_ENTITY_EXTRACTION_PROMPT= """
You are an expert system tasked with extracting entities, concepts/symbols and relationships
from Jorge Luis Borges' corpus. **Your primary goal is maximum recall: identify and extract *every*
potential entity mentioned in the provided text chunk, even if mentioned briefly or
ambiguously.**

Follow these detailed guidelines:

**Step 1: Entity Extraction - Be Comprehensive**
            *   Scan the text chunk carefully and identify all the below entities:
                - **Named entities**: people, places, organizations, works (books, poems, etc.), historical 
                    figures, events, institutions, movements, events.
                - **Compound noun phrases functioning as entities**: These refer to a specific,
                    contextualized entity/location/object in Borges's life.
                - **Identify Biographically Significant Places:** Any description of a physical location where Borges or his family lived, stayed, or had memories is ALWAYS an entity. This includes villas, houses, streets, patios, gardens, and similar references — even if not proper nouns.
                - **Concepts/symbols**: recurring Borges themes or culturally/historically relevant concepts 
            *   Consider Minor Mentions: Do not omit entities just because they seem minor or are 
mentioned in passing or lack extensive context within this specific chunk. If a name appears, extract it.
            *   Contextual Resolution: Actively resolve pronouns (he, she, it, they) and ambiguous 
references (e.g., 'the author', 'the city', 'his sister') to the specific named entity they refer to within 
the chunk's context. 
Do not invent resolutions for vague references. If a person is referred to by a partial name (e.g., 'Dr. 
Johnson', 'Victoria'), use your knowledge to determine the full name. 
            *   Extract broad contextual entities (e.g., "Argentine poets," 
"tramcars in Argentina") when the chunk strongly implies their relevance, even if not explicitly foregrounded.

**Step 2: Entity Relevance:**
            *   For each extracted entity, determine its relevance within the sentence or paragraph in which it appears:
                - Assign the tag **TOPIC** to entities that are an important or central subject of the sentence or paragraph. These are entities about which the text is making a substantive statement or providing significant information. For example, in the sentence “Palermo was on the shabby northern outskirts of town,” the entity "Palermo" is the focus of the statement and should be labeled as **TOPIC**.
                - Assign the tag **SECONDARY** to entities that are mentioned only in passing, as background, or as part of a description of another entity or event. For example, in the sentence “My grandparents married in Paraná, the capital city of Entre Ríos,” the entity “Entre Ríos” is referenced only to provide context for “Paraná” and should be labeled as **SECONDARY**.
            *   Carefully consider the role each entity plays in the immediate context, prioritizing the identification of central topics while ensuring that all entities, even those mentioned briefly, are assigned an appropriate relevance tag.            

**Step 3: Entity Classification:** 
            *   Classify each **extracted entity** according to the following categories and sub
categories. Please note that there are different categories for *concepts* and for *specific 
instances* of those concepts. For example, the entity “book” in the text “Books are an extension of 
the imagination” should be classified in category 2.B, as it refers to “The Book / Books as a 
concept”, while the entity “Divine comedy” should be classified in 1.B, as it is a specific book. 
For each entity, you should find the appropriate *Category* (numbered with letters) and *Sub
Category* (listed with numbers within each Category). 

This is the list of Categories and Sub-Categories, followed by the TYPE, that is one of PERSON, 
CONCEPT, LITERARY WORK, WORK OF ART, LANGUAGE AND LITERATURE, EVENT, 
PLACE, INSTITUTION.
A. Literature, the humanities, including philosophy and the arts
    1. WRITING
        1. Writing as a concept, for example as an occupation, as an art form, etc. /
        CONCEPT
        2. Writers, authors or translators of literary, artistic or philosophical works, like Shakespeare,
        Cervantes, Güiraldes, Spencer, William James, Henry James, David Hume, Edward Lane
        and many others. / PERSON
    2. BOOKS, POEMS, ESSAYS AND PLAYS
        1. The Book / Books as a concept, for example in references like "books are an extension of
        the imagination" / CONCEPT
        2. Specific books, like the Divine Comedy / LITERARY WORK
        3. Other specific literary works, like poems, essays, plays, conferences, manifestos, etc. /
        LITERARY WORK
    3. LITERARY GENRES AND THEORY
        1. Concepts, like the art of storytelling, or poetry as an art / CONCEPT
        2. Literary genres, including realism, detective fiction, fantastic literature, poetry, essays,
        chronicles, book or film review, etc / LITERARY WORK
        3. Techniques like the use of hypallage, anaphora, allegory, symbolism, foreshadowing,
        stream of consciousness or metonymy / LITERARY WORK
    4. TRANSLATIONS
        1. Translation as a concept, as in discussions of different ways of translating, from more literal
        to more liberal, the role of the translator / CONCEPT
        2. Translations, meaning specific instances, like Baudelaire's translations of Edgar Allan Poe. /
        LITERARY WORK
    5. ART
        1. Art, artistic styles and concepts, like Italian art, Japanese painting or realism in art /
        CONCEPT
        2. Art and specific artworks, such as Xul Solar's paintings / WORK OF ART
    6. MUSIC
        1. Music as a concept, including related ideas such as harmony / CONCEPT
        2. Musical genres, like jazz, the tango, the milonga or the blues / CONCEPT
        3. Music and musical works, like "La Cumparsita" / WORK OF ART
    7. FILM
        1. Film as a concept, that is, film as an art form, and discussions on dubbing vs. subtitles, or
        silent movies vs. talkies. / CONCEPT
        2. Films, like Charlie Chaplin's Citi lights / WORK OF ART
        3. Film directors and actors, like King Vidor or Joseph von Sternberg / PERSON
    8. LANGUAGE
        1. Language in general, including linguistics and philology. / CONCEPT
        2. Languages, like Spanish, French or German, for example in discussions about how easy or
        difficult each language is, how Borges learnt Italian with a bilingual edition of the Divine
        Comedy / LANGUAGE AND LITERATURE
    9. LITERATURE AND LITERARY THEORY
        1. Literatures of the world, like French, English or Argentine literature. Awards and prizes in
        literature, like the Nobel Prize / LANGUAGE AND LITERATURE
    10. Awards and prizes in general, for example in references like "the real prize is thinking and
    reading". / CONCEPT
B. Borges's work (that is: the books, essays, poems, etc, written by Borges, includes both
published and unpublished work, for example manuscripts or book projects never realized).
    1. Books / LITERARY WORK
    2. Stories / LITERARY WORK
    3. Poems / LITERARY WORK
    4. Essays / LITERARY WORK
    5. Book or film reviews / LITERARY WORK
    6. Conferences or classes, including both transcripts and published versions of these / LITERARY
    WORK
    7. Translations / LITERARY WORK
    8. Collaborations including those with Adolfo Bioy Casares, María Esther Vázquez and Alicia
    Jurado / LITERARY WORK
    9. Letters, including published collections and unpublished ones / LITERARY WORK
C. History, religion, politics and public life
    1. Historical figures, for example Napoleon or Julius Cesar / PEOPLE
    2. Religions and religious studies, including specific concepts like Judaism, Kabbalah, Christianity,
    Buddhism and Islam / CONCEPT
    3. Figures related to current affairs (politicians like Argentina's President Raúl Alfonsín,
    Argentina's national football team's coach César Menotti, tennis player Guillermo Vilas) /
    PEOPLE
    4. Historical periods like the Middle Ages, the Inter-war years, or 19th century / CONCEPT
    5. Historical events, including battles, revolutions, wars, invasions, etc. / EVENT
    6. Current affairs events, like the Nobel Prize being awarded to Gabriel García Marquez, the
    Falkland / Malvinas War, or the landing on the Moon / EVENT
    7. Sports and popular culture
    1. As concepts, like football or tennis / CONCEPT
    2. Specific instances, like the 1978 Football World Cup / EVENT
    3. Specific people like football or tennis players, or popular singers
    8. Historical Concepts ant Theories, including The Role of Heroes/Great Individuals, Historical
    Memory & Amnesia, The Construction of National Myths, Historical Recurrence ("Eternal
    Return" applied to history) / CONCEPT
    9. Political Concepts & Ideologies including Anarchism, Liberalism, Fascism, Communism,
    Nationalism & Patriotism, Totalitarianism vs. Individual Liberty, Utopia and Dystopia, etc /
    CONCEPT
    10. Religious & Theological Concepts, like Heresy, Orthodoxy, Mysticism, Faith, Sin, Redemption,
    Grace, Sacred and Profane, Kabalah / CONCEPTS

    11. Mythological & Folklore Concepts, like Archetypes, Heroes, the Flood, Cosmogony, the
    Genesis creation narrative, legends, fairy tales or folk tales, fables, Myth as collective memory,
    etc / CONCEPT
    12. Socio-cultural concepts like traditions vs modernity, cultural identity, populism and mass media,
    civilization vs. barbarism / CONCEPT
    13. War and conflicts, including War Theory, Strategy, the psychology of enmity / CONCEPT
    14. Time and temporality in History, including Nostalgia, Ruins and Decay, linear or cyclical time,
    anachronism, zeitgeist, palimpsest, utopia and dystopia / CONCEPT
    15. Ethics and Moral Philosophy, including Justice (Divine or social), courage, betrayal and honor,
    moral relativism, free will / CONCEPT
D. Places, including geographical places, buildings and institutions
    1. Countries / PLACE
    2. Cities / PLACE
    3. Neighborhoods or streets / PLACE
    4. Mountains / PLACE
    5. Rivers / PLACE
    6. Famous buildings / PLACE
    7. Regions (ex: Europe, Northern Italy, etc) / PLACE
    8. Libraries: real ones, including Borges's father library, Miguel Cané library and the National
    Library of Argentina / INSTITUTION
    9. Other institutions, including the S.A.D.E., La Nación newspaper, etc / INSTITUTION
    10. Other physical places, not included in the above / PLACE
E. Biography (Borges's life)
    1. Friends and acquaintances / PEOPLE
        1. Friends
        2. Members of his literary circle, colleagues
        3. Acquaintances
    2. Family members / PEOPLE
    3. Places or cities where Borges lived / PLACE
    4. Places or cities that Borges visited / PLACE
    5. Life events, including travels, professional appointments, personal experiences, historical
    events impacting him, conferences given, books published, marriage, etc. / EVENT
F. Recurrent symbols and metaphors in Borges's work
    1. Mirrors / SYMBOL
    2. Encyclopaedias / SYMBOL
    3. Labyrinths / SYMBOL
    4. Tigers / SYMBOL
    5. Swords and daggers / SYMBOL
    6. Memory / SYMBOL
    7. Time and Eternity / SYMBOL
    8. The infinite / SYMBOL
    9. The double / SYMBOL
    10. Writing, including the act of writing, the writer's profession or skills / SYMBOL
    11. Books, considered as physical objects, as distinct from titles / SYMBOL
    12. Gardens / SYMBOL
    13. Coins / SYMBOL
    14. Dreams / SYMBOL
    15. Circularity / SYMBOL
    16. Maps / SYMBOL
    17. Colors / SYMBOL
    18. The past, childhood and memory places / SYMBOL
G. Core philosophical or conceptual themes in Borges's work
    1. Writing, including writing as an occupation, writing habits, etc. / CONCEPT
    2. Idealism vs. Realism / CONCEPT
    3. The Nature of Time (Circular, Branching, Subjective) / CONCEPT
    4. Identity & The Self (The Double is a symbol for this) / CONCEPT
    5. Reality vs. Illusion/Dream / CONCEPT
    6. The Nature of Infinity / CONCEPT
    7. The Paradox / CONCEPT
    8. The Nature of Language & Naming / CONCEPT
    9. Memory & Forgetting / CONCEPT
    10. Fate, Chance, & Free Will / CONCEPT
    11. The Search for Meaning/Order / CONCEPT
    12. The Author/Reader relationship / CONCEPT
    13. The Nature of Knowledge & Encyclopedias/Libraries (the concept, distinct from the symbol) /
    CONCEPT
H. Science and mathematics
    1. Mathematicians like Georg Cantor, Bertrand Russell, Zeno, Pythagoras / PEOPLE

    2. Scientists, like Einstein, Newton or Descartes / PEOPLE
    3. Mathematical concepts like infinity, paradoxes like the Russell paradox or the Zeno paradox,
    the fourth dimension, combinatorics and probability.
I. Literary Fiction and Fictional Constructs: entities originating in fictional texts (Borges's or
others'), treated as autonomous artifacts within analysis.
    1. Fictional characters and persons including human characters (like Erik Lönnot), authors (like
    Bustos Domecq) or historical figures reimagined, like Cervantes in Pierre Menard / FICTION
    2. Fictional places and geographies, including fictional cities like Uqbar, fictional architectures
    like the Library of Babel and fictional cosmologies like Tlön's planetary system. / FICTION
    3. Fictional books and texts, like the First Encyclopaedia of Tlön, or The approach to Al-Mutasim
    4. Fictional authors like Herbert Quain or Mir Bahadur Ali. / FICTION
    5. Fictional paratexts and objects like apocryphal footnotes / FICTION
    6. Fictional philosophies and systems, like Tlön's idealism, Tlön's languages, Babylon's Lottery
    rules / FICTION 
         
** In the case that an entity does not belong to **any** of the above, or in doubt, please classify the 
entity as “OTHER”, but in no case you should create new categories. So every entity should be 
classified in one or the above, or as “OTHER”** 

**Step 4: Vertical Keyword Generation**
        After classifying an entity, you must assign "Vertical Keywords". These are objective, factual keywords based on common knowledge. Generate them STRICTLY according to the rules and predefined lists below. For keywords with conditional values, you must first determine the entity's context (e.g., Western, Argentine, Non-Western) and then select a value ONLY from the corresponding list.

        IMPORTANT: The temporal keyword must reflect the entity's actual historical context of origin or 
existence, NOT the time when Borges encountered or described it.
        
        **A. Predefined Keyword Categories and Values (Use ONLY these):**

        **A. Temporal Keywords (apply hierarchy based on entity type)**
        1. **For Books, Texts, or Works of Art**  
            - Assign `year:` of first publication (if known).  
            - If exact year unknown, assign `decade:` of publication.
            - Example: *William James's "The Principles of Psychology"* → `year:1890`.

        2. **For Events**  
            - Assign `decade:` of occurrence.  
            - If spanning longer, assign `century:` as well.  
            - Example: *Argentine War of Independence* → `decade:1810s`, `century:19th`.  

        3. **For Individuals (people)**  
            - Assign `century:` corresponding to their primary period of life or activity.  
            - Example: *William James* → `century:19th`.

        4. **For Places / Institutions**  
            - If historically founded or significant in a specific era, assign `year:` or `century:` accordingly.  
            - If no founding date is relevant, skip temporal assignment.

        5. **Multiple Mentions of Same Entity**  
            - Always normalize temporal keywords to the entity's **true historical context**.  
            - If Borges mentions William James in the 1920s, still use `century:19th` and `year:1890` (for a book), 
                NOT `decade:1920s`.  
            - If context requires, you may include both (`year:1890`, `century:19th`) but avoid contradictions.  

        **2. GEOGRAPHICAL KEYWORDS** (free text value)
        *   `country:` (e.g., `country:france`)
        *   `city:` (e.g., `city:montevideo`)
        *   `region:` (e.g., `region:mesopotamia`)
        
        **3. LITERATURE, ART & HISTORY KEYWORDS (CONDITIONAL)**

        *   **`literary_period:`** - Based on the entity's context, select ONE from the appropriate group:
            *   **For Western Tradition:** `classical_antiquity`, `medieval`, `renaissance`, `baroque`, `enlightenment`, `neoclassicism`, `romanticism`, `victorian`, `realism_or_naturalism`, `modernism`, `post_modernism`.
            *   **For Argentine and Spanish-language literature:** `spanish_golden_age`, `gauchesca_literature`, `modernismo`, `avant_garde`, `ultraism`.
            *   **For non-Western and Ancient Traditions:** `anglo_saxon`, `norse`, `biblical`, `classical_persian`, `classical_arabic`, `classical_indian`, `classical_chinese`.

        *   **`art_period:`** - Based on the entity's context, select ONE from the appropriate group:
            *   **For Western Tradition:** `medieval`, `gothic`, `renaissance`, `baroque`, `romanticism`, `realism`, `impressionism`, `expressionism`, `surrealism`, `cubism`, `abstraction`.
            *   **For Argentine and Latin-American art:** `modernismo`, `martinfierrismo`.
            *   **For Non-Western art:** `islamic_art`, `eastern_art`.

        *   **`historic_period:`** - Based on the entity's context, select ONE from the appropriate group:
            *   **For Antiquity / Foundational Myths:** `classical_antiquity`, `ancient_egypt`, `ancient_judea`, `persian_empire`.
            *   **For Medieval and Early Modern:** `early_middle_ages`, `late_middle_ages`, `islamic_golden_age`, `crusades`, `mongol_empire`, `siglo_de_oro`.
            *   **For Argentina:** `spanish_colonization`, `argentine_war_of_independence`, `argentine_centennial`, `caudillos_and_civil_war`, `conquest_of_the_desert`, `generation_of_1880`, `the_years_of_argentine_centennial`, `the_inter_war_years_in_argentina`, `spanish_civil_war`, `world_war_ii`, `peronism`, `argentina_dirty_war`, `malvinas_war`.

        **4. DESCRIPTIVE KEYWORDS (NON-CONDITIONAL LISTS)**
        *   `genre:`: `fiction`, `detective_fiction`, `literary_hoax`, `philosophical_essay`, `fantastic_literature`, `essay`, `gaucho_literature`, `epic_poetry`, `short_story`, `realism`, `parable`, `dream`, `novel`, `criticism`, `sonnet`, `book_review`, `film_review`, `mini_biography`.
        *   `theme:`: `betrayal`, `infinity`, `jewish_mysticism`, `idealism`, `realism`, `simulation`, `limits_of_knowledge`, `classification_systems`, `memory`, `immortality`, `circular_time`, `eternal_return`, `parallel_universes`, `authorship`, `influence`, `translation`, `violence`, `heroism`, `totalitarianism`, `identity_and_self`, `fate_vs_chance`.
        *   `activity:`: `writer`, `philosopher`, `theologian`, `essayist`, `professor`, `military`, `sports`, `tennis`, `football`, `politician`, `soldier`, `judge`, `lawyer`, `poet`, `novelist`, `short_story_writer`, `playwright`, `musician`, `actor`, `artist`, `film_director`, `bookseller`, `literary_critic`, `translator`, `explorer`, `librarian`, `gaucho`, `compadre`.
        *   `author:` (free text value, e.g., `author:Dante Alighieri`)
        *   `language:` (free text value, e.g., `language:italian`)

        **5. BIOGRAPHICAL KEYWORDS (for Borges's life events ONLY)**
        *   `life_period:`: `before_birth`, `birth_tucuman_street`, `childhood_in_palermo`, `first_readings`, `summer_in_villa_esther_montevideo`, `first_writings`, `vacations_in_adrogue`, `geneva`, `first_trip_to_spain`, `Mallorca`, `Seville`, `Madrid`, `1921_return_to_buenos_aires`, `the_1920s`.
        *   `source:`: `external` for objective, observable facts like a travel or a prize.  `autobiographical` for personal ideas, experiences or feelings conveyed by Borges himself, for example his first experience of the Pampas, his falling in love, his excitement when discovering an author for the first time. `inferred` for all other personal information not conveyed by Borges, like his being in love with Norah Lange, a fact that Borges never recognized.
        ---

        4.  **How to format the fields - Based *Only* on Chunk Context (+ Your Knowledge for 
Name/Identification):** 
            *   For each extracted entity, provide: 
                - **Name (Normalized):** 
                    - For PEOPLE entities, normalize the name to **'Last Name, First Name (Birth Year - 
Death Year)'**. Use your general knowledge to find the full name and dates. If birth/death years are 
unknown, use the format **'Last Name, First Name'**. Example: "Johnson, Samuel (1709 - 1784)" 
or "Doe, John". 
                    - For all other entities (Works, Places, Concepts, etc.), use the most common, 
complete, and unambiguous identifier found in the text or inferred from context. 
                - **Relevance:** The relevance of the entity within the sentence or paragraph (**TOPIC** or **SECONDARY**)
                - **Category:** The specific category
                - **Sub-category:** The specific sub category
                - **Type:** The specific type
                - **Vertical Keyword:** A list of `key:value` strings generated
                - **Identification:**
                    - This field provides a concise, factual, *context-independent* definition of the entity.
                    - Write **only one short sentence**.
                    - Do **not** include the entity name at the start.
                    - The sentence should read naturally as background information, not as a label.
                    - Include only:
                        * The essential encyclopedic fact about what or who the entity is.
                        * Optionally, a brief phrase (not a full sentence) connecting its general relevance to Borges.
                    - Avoid:
                        * Any details that come specifically from the current chunk.
                        * Multiple sentences or conjunctions that make it long.

                - **Description (Chunk Summary):**
                    - This field summarizes the **specific information found only in the current text chunk** about the entity.
                    - Write in a clear, factual tone, **not** starting with phrases like “In this passage” or “Here, it says that”.
                    - Include all notable details, events, relationships, or anecdotes explicitly mentioned in this chunk.
                    - Do **not** restate general facts already given in the `Identification`.
                    - Maintain a neutral, narrative style that could stand alone as a factual summary. 

                - **References:** 
                    - Extract the exact quote(s) or paraphrase(s) from **this chunk** that directly mention 
or clearly pertain to the entity. 
                    - Assign a reference category (biographical/criticism/influence/collaboration/mention/
 discovery). Use 'mention' if unsure. 
                    - Include the source document name and chunk ID (provided in the input). 
        4. Relationships (for *each* entity) - BORGES-CENTRIC APPROACH: 
            *   **PRIORITIZATION RULE**: Focus on relationships that either involve Borges/his family 
OR are essential for navigation (authorship, geography, family trees). 
            *   **FILTERING RULE**: Avoid relationships between two entities where neither is Borges
related UNLESS they are essential factual relationships (e.g., AUTHOR_OF, LOCATED_IN). 
            *   For each entity, identify relationships that *originate from it* and point to other entities in 
the *same chunk* OR well-known entities inferable from context. 
            *   In addition to relationships between entities in the chunk or well-known entities, include 
relationships to predefined **high-level contextual entities** (e.g., 'Argentine History', 'English 
Literature') when supported by the chunk. 
            *   The `Relationship` object must specify: 
                - `relationship_type`: MUST be from the predefined list below 
                - `target_entity_name`: Normalized name of target entity (can be from same chunk OR 
external knowledge like "Argentina" for Buenos Aires) 
                - `evidence_text`: Supporting quote from chunk 
                - `relationship_relevance`: Set appropriately based on Borges connection 
            **RELATIONSHIP CATEGORIES & USAGE RULES:** 
            **A. ESSENTIAL RELATIONSHIPS (Always include if applicable):** 
                `AUTHOR_OF` - Core authorship relationships 
                `WRITTEN_BY` - Inverse authorship (Work -> Author) 
                `BORN_IN` - Birth location (Person -> Place) 
                `DIED_IN` - Death location (Person -> Place)  
                `LOCATED_IN` - Geographic containment (Place -> Place) 
                `NATIONALITY_OF` - Citizenship/origin (Person -> Country) 
            **B. FAMILY RELATIONSHIPS (Include ONLY for Borges family members):** 
                `FATHER_OF`, `MOTHER_OF`, `SON_OF`, `DAUGHTER_OF` 
                `SISTER_OF`, `BROTHER_OF`, `SPOUSE_OF` 
                *Usage*: Only create these for Borges related Entities. Be very Mindful while extracting 
Family Relationships. 
            **C. LITERARY/INTELLECTUAL RELATIONSHIPS (Include if Borges-related):** 
                `INFLUENCED_BY` - Literary/intellectual influence (prioritize Borges connections) 
                `INFLUENCES` - Exerts influence on (prioritize from Borges) 
                `TRANSLATED_BY` - Translation relationship 
                `COLLABORATED_WITH` - Literary collaboration 
                `PRAISES` - Critical appreciation 
                `CRITICIZES` - Critical analysis 
                *Usage*: Include if source OR target is Borges, or if relationship is explicitly discussed in 
detail. 
            **D. CATEGORICAL RELATIONSHIPS (Use specific variants):** 
                `BELONGS_TO_MOVEMENT` - Literary/artistic movements (instead of generic 
MEMBER_OF) 
                `PART_OF_COLLECTION` - Part of a book/anthology (instead of generic PART_OF) 
                `REPRESENTS_GENRE` - Genre classification 
                `FROM_PERIOD` - Historical period association 
            **E. SYMBOLIC/THEMATIC RELATIONSHIPS:** 
                `CONTAINS_SYMBOL` - Work contains symbolic element 
                `SYMBOLIZES` - Entity represents concept 
                `EXEMPLIFIES` - Entity is example of concept 
                `PART_OF` - relationship type for linking entities to high-level contextual entities unless a 
more specific type applies (e.g., NATIONALITY_OF for people). 
            **F. DEPRECATED - DO NOT USE:** 
                `MENTIONS` - Too generic, provides no navigation value 
                `MEMBER_OF` - Too broad, use specific variants 
                `BELONGS_TO` - Too vague, use specific variants 
                 
            **EXTERNAL KNOWLEDGE INTEGRATION:** 
            You may create relationships to well-known entities not explicitly mentioned in the chunk 
when the relationship is obvious: 
            - Cities -> Countries (Buenos Aires -> Argentina) 
            - Famous works -> Authors (Don Quixote -> Cervantes, Miguel de) 
            - Historical figures -> Nationalities 
            - Universities -> Cities/Countries 
        Remember: Your primary goal is **MAXIMUM RECALL**. You must strive to capture every potential entity.It is better to be over-inclusive than to miss an entity mentioned in the text. Extract as many entities as you can.
        Adhere strictly to the schema for output.
        """