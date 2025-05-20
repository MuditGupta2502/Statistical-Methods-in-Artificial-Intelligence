import re
from collections import defaultdict, Counter
from nltk.tokenize import word_tokenize, sent_tokenize
import math

class NgramCharacterModel:
    def __init__(self, corpus, n):
        """Initialize the n-gram character model with a given corpus and context length n."""
        self.n = n
        self.counts = [defaultdict(lambda: defaultdict(int)) for _ in range(n + 1)]
        self.contexts = [defaultdict(int) for _ in range(n + 1)]

        # Process corpus: normalize text and remove unnecessary characters
        corpus = re.sub(r'[^a-zA-Z\s]', '', corpus.lower())
        corpus = re.sub(r'\s+', ' ', corpus).strip()

        sentences = sent_tokenize(corpus)
        words = []
        
        for sentence in sentences:
            tokens = word_tokenize(sentence)
            if tokens:
                words.extend(['^'] * n + tokens + ['$'])
        
        self.words = list(set(w for w in words if w not in {'^', '$'}))
        corpus = ' '.join(words)
        self.word_freq = Counter(words)
        
        self._train(corpus)
        self._calculate_backoff_weights()

    def _train(self, corpus):
        """Train the model by collecting n-gram statistics."""
        for i in range(len(corpus) - self.n + 1):
            for j in range(1, self.n + 1):
                if i >= j - 1:
                    context = corpus[i - (j - 1):i]
                    next_char = corpus[i]
                    self.counts[j][context][next_char] += 1
                    self.contexts[j][context] += 1

    def _calculate_backoff_weights(self):
        """Compute backoff weights for smoothing."""
        self.backoff_weights = [defaultdict(float) for _ in range(self.n + 1)]
        for j in range(2, self.n + 1):
            for context in self.contexts[j]:
                shorter_context = context[1:]
                self.backoff_weights[j][context] = 0.4 if shorter_context in self.contexts[j - 1] else 0.1

    def get_char_probability(self, context, char):
        """Estimate the probability of a character based on its context."""
        max_order = min(len(context) + 1, self.n)
        for j in range(max_order, 0, -1):
            curr_context = context[-(j - 1):]
            if curr_context in self.counts[j]:
                total_count = self.contexts[j][curr_context]
                char_count = self.counts[j][curr_context].get(char, 0)
                if total_count:
                    alpha = 0.01
                    vocab_size = 27
                    prob = (char_count + alpha) / (total_count + alpha * vocab_size)
                    return prob
        return 1.0 / 27

    def get_word_probability(self, context, word):
        """Estimate word probability using character-level probabilities."""
        if not word.startswith(context):
            return 0.0
        
        log_prob = 0.0
        curr_context = context[-min(len(context), self.n - 1):]
        
        for char in word[len(context):]:
            char_prob = self.get_char_probability(curr_context, char)
            if char_prob > 0:
                log_prob += math.log(char_prob)
            else:
                return 0.0
            curr_context = (curr_context + char)[-min(len(curr_context) + 1, self.n - 1):]
        
        prob = math.exp(log_prob)
        freq_boost = math.log(1 + self.word_freq.get(word, 0)) / 10.0
        length_penalty = 1.0 / (1.0 + 0.1 * (len(word) - len(context)))
        return prob * (1.0 + freq_boost) * length_penalty

    def predict_top_words(self, context, top_k=10):
        """Retrieve the most probable words given a context."""
        context = context.lower()
        candidates = [word for word in self.words if word.startswith(context)]
        scored_candidates = [(word, self.get_word_probability(context, word)) for word in candidates]
        return sorted(scored_candidates, key=lambda x: x[1], reverse=True)[:top_k]

    def _generate_word(self, prefix):
        """Generate the most probable word completion."""
        top_words = self.predict_top_words(prefix.lower(), 1)
        return top_words[0][0] if top_words else None

    def _word_probability(self, word):
        """Retrieve the probability of a given word."""
        return self.get_word_probability('', word)
