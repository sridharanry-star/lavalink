const { rankTracks, validateAndScore } = require('./ml_ranker');

const query = 'Adhagappattathu Magajanangalay Yaenadi';
const tracks = [
  { info: { title: 'Adhagappattathu Magajanangalay Yaenadi 1 Hour Loop [Bass Boosted]', author: 'Random User', length: 3600000 } },
  { info: { title: 'Adhagappattathu Magajanangalay Public Reaction & Review', author: 'Cinema News', length: 600000 } },
  { info: { title: 'Yaenadi - D. Imman (Cover Song by Amateur)', author: 'Cover Singer', length: 210000 } },
  { info: { title: 'Yaenadi (From "Adhagappattathu Magajanangalay")', author: 'D. Imman - Topic', length: 264000 } },
  { info: { title: 'Adhagappattathu Magajanangalay - Yaenadi Video Song | D. Imman', author: 'SonyMusicSouthVEVO', length: 270000 } }
];

const ranked = rankTracks(query, tracks);
console.log('Query:', query);
console.log('Total input:', tracks.length, '| Ranked results:', ranked.length);
ranked.forEach((t, i) => console.log(`#${i + 1}: ${t.info.title} (${t.info.author})`));
