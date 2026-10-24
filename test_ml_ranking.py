import ml

query = "Adhagappattathu Magajanangalay Yaenadi"
candidates = [
    {
        "title": "Adhagappattathu Magajanangalay Yaenadi 1 Hour Loop [Bass Boosted]",
        "uploader": "Random User",
        "duration": 3600,
        "source": "youtube"
    },
    {
        "title": "Adhagappattathu Magajanangalay Public Reaction & Review",
        "uploader": "Cinema News",
        "duration": 600,
        "source": "youtube"
    },
    {
        "title": "Yaenadi - D. Imman (Cover Song by Amateur)",
        "uploader": "Cover Singer",
        "duration": 210,
        "source": "youtube"
    },
    {
        "title": "Yaenadi (From \"Adhagappattathu Magajanangalay\")",
        "uploader": "D. Imman - Topic",
        "artist": "D. Imman, Naresh Iyer",
        "duration": 264,
        "source": "ytm_song",
        "is_studio_song": True
    },
    {
        "title": "Adhagappattathu Magajanangalay - Yaenadi Video Song | D. Imman",
        "uploader": "SonyMusicSouthVEVO",
        "artist": "D. Imman",
        "duration": 270,
        "source": "youtube"
    }
]

ranker = ml.SearchRankingModel()
results = ranker.rank_candidates(query, candidates)
print(f"Query: {query}")
print(f"Total candidates passed: {len(candidates)}, Validated & ranked: {len(results)}")
for rank, (score, cand) in enumerate(results, 1):
    print(f"#{rank} [Score: {score:.1f}] {cand['title']} (Uploader: {cand.get('uploader')})")
