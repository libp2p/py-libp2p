"""
Real-time Whiteboard Demo

A collaborative whiteboard application demonstrating browser-to-backend P2P sync.
Multiple users can draw, annotate, and collaborate on a shared canvas.
"""

import argparse
import asyncio
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import trio

from browser_client import BrowserSyncClient
from sync_protocol import OperationType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ShapeType(Enum):
    """Types of shapes that can be drawn."""
    LINE = "line"
    RECTANGLE = "rectangle"
    CIRCLE = "circle"
    TEXT = "text"
    ERASER = "eraser"


@dataclass
class Point:
    """Represents a point on the canvas."""
    x: float
    y: float

    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "Point":
        return cls(x=data["x"], y=data["y"])


@dataclass
class Shape:
    """Represents a shape on the whiteboard."""
    id: str
    type: ShapeType
    points: List[Point]
    color: str
    stroke_width: float
    client_id: str
    timestamp: float
    text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "points": [p.to_dict() for p in self.points],
            "color": self.color,
            "stroke_width": self.stroke_width,
            "client_id": self.client_id,
            "timestamp": self.timestamp,
            "text": self.text
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Shape":
        return cls(
            id=data["id"],
            type=ShapeType(data["type"]),
            points=[Point.from_dict(p) for p in data["points"]],
            color=data["color"],
            stroke_width=data["stroke_width"],
            client_id=data["client_id"],
            timestamp=data["timestamp"],
            text=data.get("text")
        )


class CollaborativeWhiteboard(BrowserSyncClient):
    """
    Collaborative whiteboard with real-time synchronization.
    
    Features:
    - Real-time drawing and annotation
    - Multiple users can draw simultaneously
    - Shape synchronization
    - Color and style sharing
    - Undo/redo functionality
    """

    def __init__(self, client_id: Optional[str] = None, debug: bool = False):
        super().__init__(client_id, debug)
        
        # Whiteboard state
        self.shapes: Dict[str, Shape] = {}
        self.current_shape: Optional[Shape] = None
        self.current_color = "#000000"
        self.current_stroke_width = 2.0
        self.canvas_size = (800, 600)
        
        # Drawing state
        self.is_drawing = False
        self.last_point: Optional[Point] = None
        
        # Set up event handlers
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Set up event handlers for whiteboard operations."""
        
        def on_connected():
            print(f"✅ Connected to collaborative whiteboard as {self.client_id}")
            print("🎨 You can now start drawing!")
            print("💡 Try opening another client to see real-time collaboration")
            print("─" * 60)
        
        def on_operation(operation):
            if operation.operation == OperationType.INSERT:
                self._handle_shape_add(operation.data)
            elif operation.operation == OperationType.DELETE:
                self._handle_shape_remove(operation.data)
            elif operation.operation == OperationType.UPDATE:
                self._handle_shape_update(operation.data)
        
        def on_peer_join(data):
            peer_id = data.get("peer_id", "unknown")
            print(f"👋 {peer_id} joined the whiteboard")
        
        def on_peer_leave(data):
            peer_id = data.get("peer_id", "unknown")
            print(f"👋 {peer_id} left the whiteboard")
        
        def on_error(error):
            print(f"❌ Error: {error}")
        
        self.on('connected', on_connected)
        self.on('operation', on_operation)
        self.on('peer_join', on_peer_join)
        self.on('peer_leave', on_peer_leave)
        self.on('error', on_error)

    def _handle_shape_add(self, data: Dict[str, Any]) -> None:
        """Handle adding a new shape."""
        try:
            shape = Shape.from_dict(data)
            self.shapes[shape.id] = shape
            if self.debug:
                print(f"📥 Added shape: {shape.type.value} from {shape.client_id}")
        except Exception as e:
            logger.error(f"Error handling shape add: {e}")

    def _handle_shape_remove(self, data: Dict[str, Any]) -> None:
        """Handle removing a shape."""
        shape_id = data.get("id")
        if shape_id and shape_id in self.shapes:
            del self.shapes[shape_id]
            if self.debug:
                print(f"📥 Removed shape: {shape_id}")

    def _handle_shape_update(self, data: Dict[str, Any]) -> None:
        """Handle updating a shape."""
        shape_id = data.get("id")
        if shape_id and shape_id in self.shapes:
            try:
                updated_shape = Shape.from_dict(data)
                self.shapes[shape_id] = updated_shape
                if self.debug:
                    print(f"📥 Updated shape: {shape_id}")
            except Exception as e:
                logger.error(f"Error handling shape update: {e}")

    async def start_drawing(self, shape_type: ShapeType, point: Point) -> None:
        """Start drawing a new shape."""
        if self.is_drawing:
            await self.finish_drawing()
        
        self.is_drawing = True
        self.current_shape = Shape(
            id=f"{self.client_id}_{int(time.time() * 1000)}",
            type=shape_type,
            points=[point],
            color=self.current_color,
            stroke_width=self.current_stroke_width,
            client_id=self.client_id,
            timestamp=time.time()
        )
        self.last_point = point

    async def continue_drawing(self, point: Point) -> None:
        """Continue drawing the current shape."""
        if not self.is_drawing or not self.current_shape:
            return
        
        self.current_shape.points.append(point)
        self.last_point = point

    async def finish_drawing(self) -> None:
        """Finish drawing the current shape."""
        if not self.is_drawing or not self.current_shape:
            return
        
        # Add shape to local state
        self.shapes[self.current_shape.id] = self.current_shape
        
        # Send to other clients
        await self.send_operation(OperationType.INSERT, self.current_shape.to_dict())
        
        self.is_drawing = False
        self.current_shape = None
        self.last_point = None

    async def add_text(self, point: Point, text: str) -> None:
        """Add text at the specified point."""
        shape = Shape(
            id=f"{self.client_id}_{int(time.time() * 1000)}",
            type=ShapeType.TEXT,
            points=[point],
            color=self.current_color,
            stroke_width=self.current_stroke_width,
            client_id=self.client_id,
            timestamp=time.time(),
            text=text
        )
        
        self.shapes[shape.id] = shape
        await self.send_operation(OperationType.INSERT, shape.to_dict())

    async def remove_shape(self, shape_id: str) -> None:
        """Remove a shape by ID."""
        if shape_id in self.shapes:
            del self.shapes[shape_id]
            await self.send_operation(OperationType.DELETE, {"id": shape_id})

    async def clear_canvas(self) -> None:
        """Clear all shapes from the canvas."""
        for shape_id in list(self.shapes.keys()):
            await self.remove_shape(shape_id)

    def set_color(self, color: str) -> None:
        """Set the current drawing color."""
        self.current_color = color

    def set_stroke_width(self, width: float) -> None:
        """Set the current stroke width."""
        self.current_stroke_width = width

    def get_shapes(self) -> List[Shape]:
        """Get all shapes on the canvas."""
        return list(self.shapes.values())

    def get_shape_by_id(self, shape_id: str) -> Optional[Shape]:
        """Get a shape by ID."""
        return self.shapes.get(shape_id)

    def render_canvas(self) -> str:
        """Render the canvas as ASCII art (for demo purposes)."""
        width, height = self.canvas_size
        canvas = [[' ' for _ in range(width)] for _ in range(height)]
        
        # Draw shapes
        for shape in self.shapes.values():
            self._draw_shape_on_canvas(canvas, shape)
        
        # Draw current shape being drawn
        if self.current_shape:
            self._draw_shape_on_canvas(canvas, self.current_shape, char='*')
        
        # Convert to string
        return '\n'.join(''.join(row) for row in canvas)

    def _draw_shape_on_canvas(self, canvas: List[List[str]], shape: Shape, char: str = 'X') -> None:
        """Draw a shape on the ASCII canvas."""
        if not shape.points:
            return
        
        if shape.type == ShapeType.LINE:
            self._draw_line(canvas, shape.points[0], shape.points[-1], char)
        elif shape.type == ShapeType.RECTANGLE:
            if len(shape.points) >= 2:
                self._draw_rectangle(canvas, shape.points[0], shape.points[-1], char)
        elif shape.type == ShapeType.CIRCLE:
            if len(shape.points) >= 2:
                self._draw_circle(canvas, shape.points[0], shape.points[-1], char)
        elif shape.type == ShapeType.TEXT:
            if shape.points:
                point = shape.points[0]
                x, y = int(point.x), int(point.y)
                if 0 <= x < len(canvas[0]) and 0 <= y < len(canvas):
                    canvas[y][x] = 'T'

    def _draw_line(self, canvas: List[List[str]], start: Point, end: Point, char: str) -> None:
        """Draw a line on the canvas."""
        x0, y0 = int(start.x), int(start.y)
        x1, y1 = int(end.x), int(end.y)
        
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        
        while True:
            if 0 <= x0 < len(canvas[0]) and 0 <= y0 < len(canvas):
                canvas[y0][x0] = char
            
            if x0 == x1 and y0 == y1:
                break
            
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def _draw_rectangle(self, canvas: List[List[str]], start: Point, end: Point, char: str) -> None:
        """Draw a rectangle on the canvas."""
        x0, y0 = int(start.x), int(start.y)
        x1, y1 = int(end.x), int(end.y)
        
        for y in range(min(y0, y1), max(y0, y1) + 1):
            for x in range(min(x0, x1), max(x0, x1) + 1):
                if 0 <= x < len(canvas[0]) and 0 <= y < len(canvas):
                    canvas[y][x] = char

    def _draw_circle(self, canvas: List[List[str]], center: Point, edge: Point, char: str) -> None:
        """Draw a circle on the canvas."""
        cx, cy = int(center.x), int(center.y)
        radius = int(math.sqrt((edge.x - center.x)**2 + (edge.y - center.y)**2))
        
        for y in range(cy - radius, cy + radius + 1):
            for x in range(cx - radius, cx + radius + 1):
                if (0 <= x < len(canvas[0]) and 0 <= y < len(canvas) and
                    abs(math.sqrt((x - cx)**2 + (y - cy)**2) - radius) < 1):
                    canvas[y][x] = char

    async def interactive_mode(self) -> None:
        """Run interactive whiteboard mode."""
        print("\n🎨 Interactive Whiteboard Commands:")
        print("  l <x1> <y1> <x2> <y2>  - Draw line")
        print("  r <x1> <y1> <x2> <y2>  - Draw rectangle")
        print("  c <x1> <y1> <x2> <y2>  - Draw circle")
        print("  t <x> <y> <text>       - Add text")
        print("  d <shape_id>           - Delete shape")
        print("  clear                  - Clear canvas")
        print("  color <hex>            - Set color (e.g., #FF0000)")
        print("  width <size>           - Set stroke width")
        print("  show                   - Show canvas")
        print("  stats                  - Show statistics")
        print("  q                      - Quit")
        print("  h                      - Show this help")
        print()
        
        while True:
            try:
                command = input("\n> ").strip()
                
                if not command:
                    continue
                
                parts = command.split()
                cmd = parts[0].lower()
                
                if cmd == 'q':
                    print("👋 Goodbye!")
                    break
                elif cmd == 'h':
                    print("\n🎨 Interactive Whiteboard Commands:")
                    print("  l <x1> <y1> <x2> <y2>  - Draw line")
                    print("  r <x1> <y1> <x2> <y2>  - Draw rectangle")
                    print("  c <x1> <y1> <x2> <y2>  - Draw circle")
                    print("  t <x> <y> <text>       - Add text")
                    print("  d <shape_id>           - Delete shape")
                    print("  clear                  - Clear canvas")
                    print("  color <hex>            - Set color (e.g., #FF0000)")
                    print("  width <size>           - Set stroke width")
                    print("  show                   - Show canvas")
                    print("  stats                  - Show statistics")
                    print("  q                      - Quit")
                    print("  h                      - Show this help")
                elif cmd == 'l' and len(parts) >= 5:
                    try:
                        x1, y1, x2, y2 = map(float, parts[1:5])
                        await self.start_drawing(ShapeType.LINE, Point(x1, y1))
                        await self.finish_drawing()
                        await self.start_drawing(ShapeType.LINE, Point(x2, y2))
                        await self.finish_drawing()
                    except ValueError:
                        print("❌ Invalid coordinates. Please enter numbers.")
                elif cmd == 'r' and len(parts) >= 5:
                    try:
                        x1, y1, x2, y2 = map(float, parts[1:5])
                        await self.start_drawing(ShapeType.RECTANGLE, Point(x1, y1))
                        await self.finish_drawing()
                        await self.start_drawing(ShapeType.RECTANGLE, Point(x2, y2))
                        await self.finish_drawing()
                    except ValueError:
                        print("❌ Invalid coordinates. Please enter numbers.")
                elif cmd == 'c' and len(parts) >= 5:
                    try:
                        x1, y1, x2, y2 = map(float, parts[1:5])
                        await self.start_drawing(ShapeType.CIRCLE, Point(x1, y1))
                        await self.finish_drawing()
                        await self.start_drawing(ShapeType.CIRCLE, Point(x2, y2))
                        await self.finish_drawing()
                    except ValueError:
                        print("❌ Invalid coordinates. Please enter numbers.")
                elif cmd == 't' and len(parts) >= 4:
                    try:
                        x, y = map(float, parts[1:3])
                        text = ' '.join(parts[3:])
                        await self.add_text(Point(x, y), text)
                    except ValueError:
                        print("❌ Invalid coordinates. Please enter numbers.")
                elif cmd == 'd' and len(parts) >= 2:
                    shape_id = parts[1]
                    await self.remove_shape(shape_id)
                elif cmd == 'clear':
                    await self.clear_canvas()
                elif cmd == 'color' and len(parts) >= 2:
                    color = parts[1]
                    self.set_color(color)
                    print(f"🎨 Color set to {color}")
                elif cmd == 'width' and len(parts) >= 2:
                    try:
                        width = float(parts[1])
                        self.set_stroke_width(width)
                        print(f"📏 Stroke width set to {width}")
                    except ValueError:
                        print("❌ Invalid width. Please enter a number.")
                elif cmd == 'show':
                    print("\n" + "=" * 60)
                    print("🎨 COLLABORATIVE WHITEBOARD")
                    print("=" * 60)
                    canvas = self.render_canvas()
                    print(canvas)
                    print("=" * 60)
                    print(f"Shapes: {len(self.shapes)} | Color: {self.current_color} | Width: {self.current_stroke_width}")
                    print("=" * 60)
                elif cmd == 'stats':
                    stats = self.get_stats()
                    print(f"\n📊 Whiteboard Statistics:")
                    print(f"  Client ID: {stats['client_id']}")
                    print(f"  Connected: {stats['connected']}")
                    print(f"  Operations sent: {stats['operations_sent']}")
                    print(f"  Operations received: {stats['operations_received']}")
                    print(f"  Shapes on canvas: {len(self.shapes)}")
                    print(f"  Connected peers: {len(stats.get('connected_peers', []))}")
                else:
                    print("❌ Unknown command. Type 'h' for help.")
                
                await trio.sleep(0.1)
                
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {e}")

    async def demo_mode(self) -> None:
        """Run automated demo mode."""
        print("🎬 Starting automated whiteboard demo...")
        
        # Wait for connection
        await trio.sleep(2)
        
        # Demo drawing operations
        demo_operations = [
            ("line", Point(10, 10), Point(50, 50)),
            ("rectangle", Point(60, 10), Point(100, 50)),
            ("circle", Point(110, 30), Point(150, 70)),
            ("text", Point(10, 60), "Hello World!"),
        ]
        
        for shape_type, start, end in demo_operations:
            if shape_type == "text":
                await self.add_text(start, "Hello World!")
            else:
                await self.start_drawing(ShapeType(shape_type), start)
                await self.finish_drawing()
                await self.start_drawing(ShapeType(shape_type), end)
                await self.finish_drawing()
            
            await trio.sleep(1)
        
        # Show final result
        await trio.sleep(1)
        print("\n" + "=" * 60)
        print("🎨 COLLABORATIVE WHITEBOARD")
        print("=" * 60)
        canvas = self.render_canvas()
        print(canvas)
        print("=" * 60)
        print(f"Shapes: {len(self.shapes)}")
        print("=" * 60)
        
        print("\n🎉 Demo completed!")
        print("💡 Try opening another client to see real-time collaboration")
        
        # Keep running to receive operations
        await trio.sleep_forever()


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Collaborative Whiteboard Demo")
    parser.add_argument("--backend-url", required=True, help="Backend WebSocket URL")
    parser.add_argument("--client-id", help="Client ID (auto-generated if not provided)")
    parser.add_argument("--mode", choices=["interactive", "demo"], default="interactive",
                       help="Run mode: interactive or demo")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Create whiteboard
    whiteboard = CollaborativeWhiteboard(args.client_id, args.debug)
    
    try:
        # Connect to backend
        await whiteboard.connect(args.backend_url)
        
        # Run in specified mode
        if args.mode == "interactive":
            await whiteboard.interactive_mode()
        else:
            await whiteboard.demo_mode()
            
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        await whiteboard.disconnect()


if __name__ == "__main__":
    try:
        trio.run(main)
    except KeyboardInterrupt:
        print("\n✅ Clean exit completed.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
