import curses
import re
import sys
import os
import time
from typing import List
from ngram import NgramCharacterModel

class TerminalUI:
    def __init__(self, prediction_model, text_content=None, auto_mode=False, delay=0.5):
        self.screen = None
        self.suggestions = []
        self.current_suggestion_idx = 0
        self.scores = []
        self.text_content = text_content
        self.user_input = ""
        self.cursor_pos = 0
        self.cursor_row = 1
        self.cursor_col = 0

        self.suggestions_panel = None
        self.text_panel = None
        self.input_panel = None
        self.scores_panel = None

        self.prediction_model = prediction_model

        # Track typed letters per current word
        self.current_word_keystrokes = 0

        # (k_i, l_i) for each completed word; k_i = typed letters, l_i = final word length
        self.word_stats = []
        self.tabKeyCount = 0

        self.auto_mode = auto_mode
        self.delay = delay

    def calculate_scores(self, text: str) -> List[float]:
        """
        1) total letters typed = sum(k_i)
        2) total tab presses
        3) avg letters/word = sum(k_i)/sum(l_i)
        4) avg tabs/word = total_tab_keys/total_words
        """
        total_letters = sum(k for (k, _) in self.word_stats)
        total_tabs = self.tabKeyCount
        sum_of_final_letters = sum(l for (_, l) in self.word_stats)

        if sum_of_final_letters > 0:
            avg_letters_per_word = total_letters / sum_of_final_letters
        else:
            avg_letters_per_word = 0.0

        total_words = len(self.word_stats)
        if total_words > 0:
            avg_tabs_per_word = total_tabs / total_words
        else:
            avg_tabs_per_word = 0.0

        return [total_letters, total_tabs, avg_letters_per_word, avg_tabs_per_word]

    def find_last_word_start(self, text: str, cursor_pos: int) -> int:
        if cursor_pos == 0:
            return 0
        text_before_cursor = text[:cursor_pos]
        match = re.search(r"[^\s]*$", text_before_cursor)
        return cursor_pos - len(match.group(0)) if match else cursor_pos

    def get_current_word(self) -> str:
        word_start = self.find_last_word_start(self.user_input, self.cursor_pos)
        return self.user_input[word_start:self.cursor_pos]

    def replace_current_word(self, new_word: str) -> None:
        word_start = self.find_last_word_start(self.user_input, self.cursor_pos)
        self.user_input = (self.user_input[:word_start]
                           + new_word
                           + self.user_input[self.cursor_pos:])
        self.cursor_pos = word_start + len(new_word)

    def finalize_current_word_stats(self) -> None:
        words = self.user_input.strip().split()
        if not words:
            self.current_word_keystrokes = 0
            return

        last_word = words[-1]
        l_i = sum(1 for c in last_word if c.isalpha())  # final word length (alpha only)
        k_i = self.current_word_keystrokes

        if l_i > 0:
            self.word_stats.append((k_i, l_i))

        self.current_word_keystrokes = 0

    def draw_suggestions_panel(self) -> None:
        h, w = self.suggestions_panel.getmaxyx()
        self.suggestions_panel.erase()
        self.suggestions_panel.box()
        self.suggestions_panel.addstr(0, 2, " Suggestions ")

        if not self.suggestions:
            self.suggestions_panel.addstr(1, 2, "No suggestions")
        else:
            display_text = ""
            for i, suggestion in enumerate(self.suggestions):
                if i == self.current_suggestion_idx:
                    display_text += f"[{suggestion}] "
                else:
                    display_text += f"{suggestion} "
            if len(display_text) > w - 4:
                display_text = display_text[:w - 7] + "..."
            self.suggestions_panel.addstr(1, 2, display_text)

        self.suggestions_panel.noutrefresh()

    def draw_text_panel(self) -> None:
        h, w = self.text_panel.getmaxyx()
        self.text_panel.erase()
        self.text_panel.box()
        self.text_panel.addstr(0, 2, " Text Content ")

        words = self.text_content.split()
        lines = []
        current_line = ""
        for word in words:
            if len((current_line + " " + word).strip()) > w - 4:
                lines.append(current_line)
                current_line = word
            else:
                current_line = (current_line + " " + word).strip()
        if current_line:
            lines.append(current_line)

        for i, line in enumerate(lines):
            if i < h - 2:
                self.text_panel.addstr(i + 1, 2, line)

        self.text_panel.noutrefresh()

    def draw_input_panel(self) -> None:
        h, w = self.input_panel.getmaxyx()
        self.input_panel.erase()
        self.input_panel.box()
        self.input_panel.addstr(0, 2, " Input ")

        prompt = "> "
        prompt_len = len(prompt)
        available_width = w - 4
        first_line_width = available_width - prompt_len

        text = self.user_input
        lines = []
        first_line_text = text[:first_line_width] if text else ""
        lines.append(first_line_text)
        current_pos = len(first_line_text)

        while current_pos < len(text) and len(lines) < h - 2:
            next_chunk = text[current_pos:current_pos + available_width]
            lines.append(next_chunk)
            current_pos += len(next_chunk)

        for i, line in enumerate(lines):
            if i >= h - 2:
                break
            if i == 0:
                self.input_panel.addstr(i + 1, 2, prompt + line)
            else:
                self.input_panel.addstr(i + 1, 2, line)

        # Position cursor
        if self.cursor_pos <= first_line_width:
            cursor_y = 1
            cursor_x = 2 + prompt_len + self.cursor_pos
        else:
            pos = self.cursor_pos - first_line_width
            cursor_y = 2 + (pos // available_width)
            cursor_x = 2 + (pos % available_width)

        # Ensure cursor position is within bounds
        cursor_y = max(1, min(cursor_y, h - 2))
        cursor_x = max(2, min(cursor_x, w - 2))

        self.cursor_row = cursor_y
        self.cursor_col = cursor_x

        try:
            self.input_panel.move(cursor_y, cursor_x)
        except curses.error:
            # Fallback to a safe position if move fails
            self.input_panel.move(1, 2 + prompt_len)

        self.input_panel.noutrefresh()

    def draw_scores_panel(self) -> None:
        h, w = self.scores_panel.getmaxyx()
        self.scores_panel.erase()
        self.scores_panel.box()
        self.scores_panel.addstr(0, 2, " Scores ")
        self.scores = self.calculate_scores(self.user_input)

        score_labels = [
            "Letter Keys",
            "Tab Keys",
            "Avg Letters/Word",
            "Avg Tabs/Word",
        ]
        display_text = " | ".join(
            f"{label}: {score:.2f}" if isinstance(score, float) else f"{label}: {score}"
            for label, score in zip(score_labels, self.scores)
        )
        if len(display_text) > w - 4:
            display_text = display_text[:w - 7] + "..."
        self.scores_panel.addstr(1, max(1, (w - len(display_text)) // 2), display_text)
        self.scores_panel.noutrefresh()

    def handle_input(self, key) -> bool:
        if key == curses.KEY_RESIZE:
            return True
        if key == 27:  # ESC
            return False
        if key == 9:  # Tab
            self.tabKeyCount += 1
            if self.suggestions:
                self.current_suggestion_idx = (self.current_suggestion_idx + 1) % len(self.suggestions)
            return True
        if key == 10:  # Enter
            if self.suggestions and self.current_suggestion_idx < len(self.suggestions):
                self.replace_current_word(self.suggestions[self.current_suggestion_idx])
            self.finalize_current_word_stats()
            self.suggestions = []
            self.current_suggestion_idx = 0
            return True

        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.cursor_pos > 0:
                char_deleted = self.user_input[self.cursor_pos - 1]
                self.user_input = (
                    self.user_input[:self.cursor_pos - 1]
                    + self.user_input[self.cursor_pos:]
                )
                self.cursor_pos -= 1
                if char_deleted.isalpha() and self.current_word_keystrokes > 0:
                    self.current_word_keystrokes -= 1

                current_word = self.get_current_word()
                self.update_suggestions(current_word)
            return True

        if key == curses.KEY_LEFT:
            if self.cursor_pos > 0:
                self.cursor_pos -= 1
                current_word = self.get_current_word()
                self.update_suggestions(current_word)
            return True

        if key == curses.KEY_RIGHT:
            if self.cursor_pos < len(self.user_input):
                self.cursor_pos += 1
                current_word = self.get_current_word()
                self.update_suggestions(current_word)
            return True

        if 32 <= key <= 126:
            char = chr(key)
            self.user_input = (
                self.user_input[:self.cursor_pos] + char + self.user_input[self.cursor_pos:]
            )
            self.cursor_pos += 1

            if char.isalpha():
                self.current_word_keystrokes += 1

            if char == ' ':
                self.finalize_current_word_stats()

            current_word = self.get_current_word()
            self.update_suggestions(current_word)

        return True

    def update_suggestions(self, context: str) -> None:
        """
        To store only the words, we slice off the probability portion
        from predict_top_words result.
        """
        top_results = self.prediction_model.predict_top_words(context, top_k=10)
        self.suggestions = [item[0] for item in top_results]
        self.current_suggestion_idx = 0

    def update_ui(self):
        self.draw_suggestions_panel()
        self.draw_text_panel()
        self.draw_input_panel()
        self.draw_scores_panel()
        curses.doupdate()

    def run_automated_test(self):
        """
        Simulate typing words from text_content automatically:
        - Type one letter at a time
        - If the word appears in suggestions before fully typed, use Tab+Enter to complete it
        - If the word is already completely typed, just add a space and move to next word
        """
        words = self.text_content.split()
        for word in words:
            typed_letters = ""
            word_completed_by_suggestion = False
            
            # Type one letter at a time
            for letter in word:
                # Add the next letter
                keep_running = self.handle_input(ord(letter))
                self.update_ui()
                if not keep_running:
                    return
                time.sleep(self.delay)
                
                typed_letters += letter
                
                # If we haven't finished typing the whole word yet
                if typed_letters != word:
                    # Check if the full target word appears in current suggestions
                    if word in self.suggestions:
                        # Find the word's position in suggestions
                        target_index = self.suggestions.index(word)
                        # Press Tab enough times to select it
                        for _ in range(target_index):
                            keep_running = self.handle_input(9)  # Tab
                            self.update_ui()
                            if not keep_running:
                                return
                            time.sleep(self.delay)
                        # Press Enter to accept suggestion
                        keep_running = self.handle_input(10)  # Enter
                        self.update_ui()
                        if not keep_running:
                            return
                        time.sleep(self.delay)
                        word_completed_by_suggestion = True
                        break
            
            # Only type space if we haven't already moved on via suggestion completion
            if not word_completed_by_suggestion:
                # If we're here, we typed the entire word manually
                # Just press space to move to next word
                keep_running = self.handle_input(ord(' '))
                self.update_ui()
                if not keep_running:
                    return
                time.sleep(self.delay)
            else:
                # If we completed via suggestion, we still need to type space
                # to separate from the next word
                keep_running = self.handle_input(ord(' '))
                self.update_ui()
                if not keep_running:
                    return
                time.sleep(self.delay)
        
        # Pause at the end to see final results
        time.sleep(1)

    def run(self) -> None:
        try:
            self.screen = curses.initscr()
            curses.noecho()
            curses.cbreak()
            curses.start_color()
            self.screen.keypad(True)
            curses.curs_set(1)
            curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)

            max_y, max_x = self.screen.getmaxyx()
            suggestions_height = 3
            text_height = (max_y - 6) // 2
            input_height = (max_y - 6) // 2
            scores_height = 3

            self.suggestions_panel = curses.newwin(suggestions_height, max_x, 0, 0)
            self.text_panel = curses.newwin(text_height, max_x, suggestions_height, 0)
            self.input_panel = curses.newwin(input_height, max_x, suggestions_height + text_height, 0)
            self.scores_panel = curses.newwin(scores_height, max_x, suggestions_height + text_height + input_height, 0)

            self.update_ui()

            if self.auto_mode:
                self.run_automated_test()
                while True:
                    key = self.screen.getch()
                    if key == 27:
                        break
                    self.update_ui()
            else:
                running = True
                while running:
                    try:
                        self.input_panel.move(self.cursor_row, self.cursor_col)
                    except:
                        self.input_panel.move(1, 4)
                    self.input_panel.noutrefresh()
                    curses.doupdate()
                    key = self.screen.getch()
                    running = self.handle_input(key)

                    if key == curses.KEY_RESIZE:
                        max_y, max_x = self.screen.getmaxyx()
                        suggestions_height = 3
                        text_height = (max_y - 6) // 2 + 2
                        input_height = (max_y - 6) // 2 + 1
                        scores_height = 3
                        self.suggestions_panel = curses.newwin(suggestions_height, max_x, 0, 0)
                        self.text_panel = curses.newwin(text_height, max_x, suggestions_height, 0)
                        self.input_panel = curses.newwin(input_height, max_x, suggestions_height + text_height, 0)
                        self.scores_panel = curses.newwin(scores_height, max_x, suggestions_height + text_height + input_height, 0)

                    self.update_ui()

        finally:
            # If user quits mid-word, finalize it
            self.finalize_current_word_stats()

            if self.screen:
                curses.nocbreak()
                self.screen.keypad(False)
                curses.echo()
                curses.endwin()

            final_scores = self.calculate_scores(self.user_input)
            print("\n========== FINAL RESULTS ==========")
            print(f"Letter Keys: {final_scores[0]}")
            print(f"Tab Keys: {final_scores[1]}")
            print(f"Avg Letters/Word: {final_scores[2]:.2f}")
            print(f"Avg Tabs/Word: {final_scores[3]:.2f}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python user_interface.py <path_to_training_corpus> [--auto]")
        sys.exit(1)

    training_path = sys.argv[1]
    auto_mode = "--auto" in sys.argv

    training_corpus = ""
    full_path = ""
    if os.path.isdir(training_path):
        for filename in sorted(os.listdir(training_path)):
            full_path = os.path.join(training_path, filename)
            if os.path.isfile(full_path):
                try:
                    with open(full_path, "r",encoding='utf8') as f:
                        training_corpus += f.read()
                except FileNotFoundError:
                    print(f"File not found: {full_path}")
                    sys.exit(1)
    else:
        try:
            with open(training_path, "r",encoding='utf8') as f:
                training_corpus = f.read()
        except FileNotFoundError:
            print(f"File not found: {training_path}")
            sys.exit(1)
    print(sys.argv[0],sys.argv[1],sys.argv[2])
    try:
        with open("text_content.txt", "r") as f:
            text_content = f.read()
            # text_content = sys.argv[2]
    except FileNotFoundError:
        print("File 'text_content.txt' not found!")
        sys.exit(1)
    print(f"full Path + {full_path}")
    n = 3
    model = NgramCharacterModel(training_corpus, n)
    ui = TerminalUI(model, text_content=text_content, auto_mode=auto_mode, delay=0.2)
    ui.run()