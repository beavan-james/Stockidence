import numpy as np


class RidgeRegression:
    def __init__(self, alpha=1.0):
        self.alpha = alpha
        self.w = None  # Weights (coefficients)
        self.b = None  # Intercept (bias)

    def fit(self, X, y):
        # 1. Convert inputs to NumPy arrays
        X = np.asarray(X)
        y = np.asarray(y)
        n_samples, n_features = X.shape

        # 2. Add a column of ones to X to handle the intercept (bias)
        X_bias = np.hstack([np.ones((n_samples, 1)), X])

        # 3. Create the modified Identity matrix (do not penalize the intercept)
        I = np.identity(n_features + 1)
        I[0, 0] = 0  # Set the top-left element to 0 for the bias term

        # 4. Solve the adjusted normal equation
        # We use np.linalg.solve instead of inv() for better numerical stability
        A = X_bias.T @ X_bias + self.alpha * I
        b_vec = X_bias.T @ y
        beta = np.linalg.solve(A, b_vec)

        # 5. Separate intercept and weights
        self.b = beta[0]
        self.w = beta[1:]

    def predict(self, X):
        X = np.asarray(X)
        return X @ self.w + self.b
