"""
Snake Game — 使用 Python 标准库 turtle 模块实现
功能：
  - 方向键控制蛇的移动方向
  - 随机生成食物
  - 吃到食物后蛇变长，分数 +10
  - 撞墙或撞到自己时游戏结束，显示最终分数
  - 窗口标题 "Snake Game — OmniAgent"
  - 得分实时显示在窗口顶部
"""

import turtle
import random
import time

# ==================== 常量配置 ====================
WINDOW_WIDTH = 600          # 窗口宽度
WINDOW_HEIGHT = 600         # 窗口高度
GRID_SIZE = 20              # 每格大小（像素）
GAME_SPEED = 100            # 游戏速度（毫秒），值越小越快
MARGIN = 10                 # 边距（防止蛇贴边）

# 计算游戏区域
PLAY_AREA_LEFT = -WINDOW_WIDTH // 2 + MARGIN
PLAY_AREA_RIGHT = WINDOW_WIDTH // 2 - MARGIN
PLAY_AREA_TOP = WINDOW_HEIGHT // 2 - MARGIN - 40   # 顶部留 40px 给分数栏
PLAY_AREA_BOTTOM = -WINDOW_HEIGHT // 2 + MARGIN

# 对齐网格的随机坐标生成
RANDOM_X_MIN = PLAY_AREA_LEFT // GRID_SIZE + 1
RANDOM_X_MAX = PLAY_AREA_RIGHT // GRID_SIZE - 1
RANDOM_Y_MIN = PLAY_AREA_BOTTOM // GRID_SIZE + 1
RANDOM_Y_MAX = PLAY_AREA_TOP // GRID_SIZE - 1

# 方向向量
DIRECTIONS = {
    "Up":    (0, GRID_SIZE),
    "Down":  (0, -GRID_SIZE),
    "Left":  (-GRID_SIZE, 0),
    "Right": (GRID_SIZE, 0),
}

# 反向映射（防止蛇直接掉头）
OPPOSITE = {
    "Up": "Down",
    "Down": "Up",
    "Left": "Right",
    "Right": "Left",
}


# ==================== 游戏类 ====================
class SnakeGame:
    """贪吃蛇游戏主类"""

    def __init__(self):
        # ---------- 窗口设置 ----------
        self.screen = turtle.Screen()
        self.screen.setup(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.screen.title("Snake Game — OmniAgent")
        self.screen.bgcolor("#1a1a2e")          # 深蓝背景
        self.screen.tracer(0)                    # 关闭自动刷新，手动控制动画
        self.screen.listen()                     # 开始监听键盘事件

        # ---------- 分数显示 ----------
        self.score_display = turtle.Turtle()
        self.score_display.hideturtle()
        self.score_display.penup()
        self.score_display.color("white")
        self.score_display.goto(0, WINDOW_HEIGHT // 2 - 35)

        # ---------- 蛇 ----------
        self.snake = []              # 蛇身段列表（每个元素是一个 Turtle）
        self.direction = "Right"     # 初始移动方向
        self.next_direction = "Right"
        self.growing = False         # 是否正在增长

        # ---------- 食物 ----------
        self.food = turtle.Turtle()
        self.food.shape("circle")
        self.food.color("red")
        self.food.penup()
        self.food.hideturtle()

        # ---------- 游戏状态 ----------
        self.score = 0
        self.running = True

        # ---------- 初始化 ----------
        self._create_snake()
        self._spawn_food()
        self._bind_keys()
        self._update_score_display()

    # ---------- 蛇的创建 ----------
    def _create_snake(self):
        """创建初始蛇（3 节）"""
        # 蛇头从中心偏左开始，方向朝右
        start_x = 0
        start_y = 0
        for i in range(3):
            segment = turtle.Turtle()
            segment.shape("square")
            segment.color("#00ff88")          # 绿色蛇身
            segment.penup()
            segment.goto(start_x - i * GRID_SIZE, start_y)
            self.snake.append(segment)

    # ---------- 键盘绑定 ----------
    def _bind_keys(self):
        """绑定方向键"""
        self.screen.onkeypress(lambda: self._set_direction("Up"),    "Up")
        self.screen.onkeypress(lambda: self._set_direction("Down"),  "Down")
        self.screen.onkeypress(lambda: self._set_direction("Left"),  "Left")
        self.screen.onkeypress(lambda: self._set_direction("Right"), "Right")

    def _set_direction(self, new_dir):
        """设置蛇的移动方向（禁止掉头）"""
        if new_dir != OPPOSITE.get(self.direction):
            self.next_direction = new_dir

    # ---------- 食物 ----------
    def _spawn_food(self):
        """在随机位置生成食物（不与蛇身重叠）"""
        while True:
            # 生成网格对齐的随机坐标
            x = random.randint(RANDOM_X_MIN, RANDOM_X_MAX) * GRID_SIZE
            y = random.randint(RANDOM_Y_MIN, RANDOM_Y_MAX) * GRID_SIZE
            # 检查不与蛇身重叠
            if all(seg.distance(x, y) > GRID_SIZE // 2 for seg in self.snake):
                break
        self.food.goto(x, y)
        if not self.food.isvisible():
            self.food.showturtle()

    # ---------- 分数显示 ----------
    def _update_score_display(self):
        """更新窗口顶部的分数"""
        self.score_display.clear()
        self.score_display.write(
            f"Score: {self.score}",
            align="center",
            font=("Arial", 18, "bold"),
        )

    # ---------- 蛇的移动 ----------
    def _move_snake(self):
        """移动蛇：头向前移动，身体跟随"""
        # 应用新的方向
        self.direction = self.next_direction
        dx, dy = DIRECTIONS[self.direction]

        # 蛇头当前位置
        head = self.snake[0]
        new_x = head.xcor() + dx
        new_y = head.ycor() + dy

        # 碰撞检测
        if not self._is_valid_position(new_x, new_y):
            self._game_over()
            return

        # 创建新的蛇头
        new_head = turtle.Turtle()
        new_head.shape("square")
        new_head.color("#00ff88")
        new_head.penup()
        new_head.goto(new_x, new_y)

        self.snake.insert(0, new_head)

        # 判断是否吃到食物
        if new_head.distance(self.food) < GRID_SIZE:
            self.score += 10
            self._update_score_display()
            self.food.hideturtle()
            self._spawn_food()
        else:
            # 没吃到食物：移除尾部
            tail = self.snake.pop()
            tail.hideturtle()
            # 简单清理（turtle 对象由垃圾回收处理）

    # ---------- 碰撞检测 ----------
    def _is_valid_position(self, x, y):
        """检查坐标是否合法（未撞墙、未撞自身）"""
        # 检查是否撞墙
        if not (PLAY_AREA_LEFT <= x <= PLAY_AREA_RIGHT):
            return False
        if not (PLAY_AREA_BOTTOM <= y <= PLAY_AREA_TOP):
            return False
        # 检查是否撞到自己（跳过最后一个，因为它马上要被删掉，除非正在增长）
        for seg in self.snake[:-1]:
            if seg.distance(x, y) < GRID_SIZE // 2:
                return False
        return True

    # ---------- 游戏结束 ----------
    def _game_over(self):
        """游戏结束，显示最终分数"""
        self.running = False

        # 整个窗口变红
        self.screen.bgcolor("#2d0a0a")

        # 创建 Game Over 文字
        game_over_text = turtle.Turtle()
        game_over_text.hideturtle()
        game_over_text.penup()
        game_over_text.color("#ff4444")
        game_over_text.goto(0, 40)
        game_over_text.write(
            "GAME OVER",
            align="center",
            font=("Arial", 36, "bold"),
        )

        # 显示最终分数
        final_score_text = turtle.Turtle()
        final_score_text.hideturtle()
        final_score_text.penup()
        final_score_text.color("white")
        final_score_text.goto(0, -20)
        final_score_text.write(
            f"Final Score: {self.score}",
            align="center",
            font=("Arial", 24, "bold"),
        )

        # 显示提示
        hint_text = turtle.Turtle()
        hint_text.hideturtle()
        hint_text.penup()
        hint_text.color("#aaaaaa")
        hint_text.goto(0, -60)
        hint_text.write(
            "Press 'r' to restart or close the window",
            align="center",
            font=("Arial", 14, "normal"),
        )

        # 绑定 R 键重新开始
        self.screen.onkeypress(self._restart, "r")

    # ---------- 重新开始 ----------
    def _restart(self):
        """重置游戏（在同一窗口中重启）"""
        # 清除所有 turtle 图形
        self.screen.clear()

        # 重置状态
        self.snake.clear()
        self.direction = "Right"
        self.next_direction = "Right"
        self.score = 0
        self.running = True

        # 恢复窗口背景
        self.screen.bgcolor("#1a1a2e")

        # 重新创建分数显示
        self.score_display = turtle.Turtle()
        self.score_display.hideturtle()
        self.score_display.penup()
        self.score_display.color("white")
        self.score_display.goto(0, WINDOW_HEIGHT // 2 - 35)
        self._update_score_display()

        # 重新创建食物
        self.food = turtle.Turtle()
        self.food.shape("circle")
        self.food.color("red")
        self.food.penup()

        # 重新创建蛇和食物位置
        self._create_snake()
        self._spawn_food()

        # 重新绑定按键（clear 后需要重新绑定）
        self._bind_keys()

        # 重新启动游戏循环
        self._start_game_loop()

    # ---------- 主循环 ----------
    def _start_game_loop(self):
        """启动 ontimer 递归游戏循环"""
        def game_tick():
            if self.running:
                self._move_snake()
                self.screen.update()
                self.screen.ontimer(game_tick, GAME_SPEED)

        game_tick()

    def run(self):
        """游戏入口：启动循环并进入 turtle 主事件循环"""
        self._start_game_loop()
        self.screen.mainloop()


# ==================== 入口 ====================
if __name__ == "__main__":
    game = SnakeGame()
    game.run()
