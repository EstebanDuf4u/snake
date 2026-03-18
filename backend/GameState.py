import random


class GameState:
    def __init__(self):
        self.snake = [[5, 5], [6, 5], [7, 5]]
        self.apple = [10, 10]
        self.score = 0
        self.direction = "right"
        self.running = False

    def reset(self):
        self.snake = [[5, 5], [6, 5], [7, 5]]
        self.apple = [10, 10]
        self.score = 0
        self.direction = "right"
        self.running = False

    def to_dict(self):
        return {
            "type": "state",
            "snake": self.snake,
            "apple": self.apple,
            "score": self.score,
            "direction": self.direction,
            "running": self.running
        }

    def tick(self):
        if not self.running:
            return

        delta = self.direction_to_delta()
        head = self.get_head()
        new_head = [head[0] + delta[0], head[1] + delta[1]]

        # collision mur
        if new_head[0] < 0 or new_head[0] >= 30 or new_head[1] < 0 or new_head[1] >= 30:
            self.running = False
            return

        # collision corps
        if new_head in self.snake:
            self.running = False
            return

        # avancer
        self.snake.append(new_head)

        # pomme mangée
        if new_head == self.apple:
            self.score += 1
            self.generate_apple()
        else:
            # déplacement normal : on retire la queue
            self.snake.pop(0)

    def direction_from_input(self, input_value):
        if input_value == "up" and self.direction != "down":
            self.direction = "up"
        elif input_value == "down" and self.direction != "up":
            self.direction = "down"
        elif input_value == "left" and self.direction != "right":
            self.direction = "left"
        elif input_value == "right" and self.direction != "left":
            self.direction = "right"

    def direction_to_delta(self):
        if self.direction == "up":
            return (0, -1)
        elif self.direction == "down":
            return (0, 1)
        elif self.direction == "left":
            return (-1, 0)
        elif self.direction == "right":
            return (1, 0)
        else:
            return (0, 0)

    def get_head(self):
        return self.snake[-1]

    def check_collisions(self):
        head = self.get_head()

        if head[0] < 0 or head[0] >= 30 or head[1] < 0 or head[1] >= 30:
            return True

        if head in self.snake[:-1]:
            return True

        return False

    def generate_apple(self):
        while True:
            new_apple = [random.randint(0, 29), random.randint(0, 29)]
            if new_apple not in self.snake:
                self.apple = new_apple
                break

