import javax.swing.*;
import java.awt.*;
public class HelloWindow {
    public static void main(String[] args) {
        SwingUtilities.invokeLater(() -> {
            JFrame window = new JFrame("My First Java App");
            window.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
            window.setSize(440, 260);
            JLabel label = new JLabel("Hello from my Java app!", SwingConstants.CENTER);
            label.setFont(new Font("SansSerif", Font.BOLD, 22));
            window.add(label);
            window.setLocationRelativeTo(null);
            window.setVisible(true);
        });
    }
}
