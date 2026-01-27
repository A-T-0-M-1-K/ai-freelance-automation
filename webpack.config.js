/**
 * Webpack Configuration for AI Freelance Automation UI
 *
 * Purpose: Build the web-based control panel, dashboard, and monitoring interface.
 * Architecture: Fully decoupled from backend logic. Communicates via REST/WebSocket APIs.
 * Features:
 *   - TypeScript + React 18 (JSX)
 *   - CSS Modules with theme support (light/dark/custom)
 *   - Code splitting & lazy loading
 *   - Hot Module Replacement (HMR) in dev
 *   - Production optimizations (minify, cache-busting, etc.)
 *   - No runtime dependencies on Python/backend
 */

const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');
const { CleanWebpackPlugin } = require('clean-webpack-plugin');
const CopyWebpackPlugin = require('copy-webpack-plugin');

// Determine build mode
const isProduction = process.env.NODE_ENV === 'production';

module.exports = {
  // Entry point for the UI application
  entry: {
    main: './ui/src/index.tsx',
  },

  // Output configuration
  output: {
    path: path.resolve(__dirname, 'ui/dist'),
    filename: isProduction ? '[name].[contenthash].js' : '[name].js',
    chunkFilename: isProduction ? '[name].[contenthash].chunk.js' : '[name].chunk.js',
    publicPath: '/', // For SPA routing
  },

  // Resolve modules and extensions
  resolve: {
    extensions: ['.ts', '.tsx', '.js', '.jsx', '.json'],
    alias: {
      '@': path.resolve(__dirname, 'ui/src'),
      '@components': path.resolve(__dirname, 'ui/src/components'),
      '@hooks': path.resolve(__dirname, 'ui/src/hooks'),
      '@utils': path.resolve(__dirname, 'ui/src/utils'),
      '@assets': path.resolve(__dirname, 'ui/src/assets'),
      '@styles': path.resolve(__dirname, 'ui/src/styles'),
    },
  },

  // Module rules for different file types
  module: {
    rules: [
      // TypeScript + JSX
      {
        test: /\.(ts|tsx|js|jsx)$/,
        exclude: /node_modules/,
        use: {
          loader: 'babel-loader',
          options: {
            presets: [
              ['@babel/preset-env', { targets: 'defaults' }],
              ['@babel/preset-react', { runtime: 'automatic' }],
              '@babel/preset-typescript',
            ],
            plugins: [
              '@babel/plugin-proposal-class-properties',
              '@babel/plugin-proposal-optional-chaining',
            ],
          },
        },
      },

      // CSS with Modules + Theme support
      {
        test: /\.module\.css$/,
        use: [
          isProduction ? MiniCssExtractPlugin.loader : 'style-loader',
          {
            loader: 'css-loader',
            options: {
              modules: {
                localIdentName: isProduction
                  ? '[hash:base64:8]'
                  : '[name]__[local]___[hash:base64:5]',
              },
              importLoaders: 1,
            },
          },
          'postcss-loader', // For autoprefixer, future theming enhancements
        ],
      },

      // Global styles (e.g., reset, fonts)
      {
        test: /^((?!\.module).)*\.css$/,
        use: [
          isProduction ? MiniCssExtractPlugin.loader : 'style-loader',
          'css-loader',
          'postcss-loader',
        ],
      },

      // Assets (images, fonts, etc.)
      {
        test: /\.(png|jpe?g|gif|svg|woff2?|eot|ttf)$/i,
        type: 'asset/resource',
        generator: {
          filename: 'assets/[hash][ext][query]',
        },
      },
    ],
  },

  // Plugins
  plugins: [
    // Clean dist folder before build
    new CleanWebpackPlugin(),

    // Generate index.html with injected bundles
    new HtmlWebpackPlugin({
      template: './ui/public/index.html',
      favicon: './ui/public/favicon.ico',
      minify: isProduction
        ? {
            removeComments: true,
            collapseWhitespace: true,
            removeRedundantAttributes: true,
            useShortDoctype: true,
            removeEmptyAttributes: true,
            removeStyleLinkTypeAttributes: true,
            keepClosingSlash: true,
            minifyJS: true,
            minifyCSS: true,
            minifyURLs: true,
          }
        : false,
    }),

    // Extract CSS into separate files (prod only)
    ...(isProduction
      ? [
          new MiniCssExtractPlugin({
            filename: '[name].[contenthash].css',
            chunkFilename: '[name].[contenthash].chunk.css',
          }),
        ]
      : []),

    // Copy static assets (e.g., robots.txt, manifest.json)
    new CopyWebpackPlugin({
      patterns: [
        { from: 'ui/public/manifest.json', to: '.' },
        { from: 'ui/public/robots.txt', to: '.' },
      ],
    }),
  ],

  // Development server (for local UI testing)
  devServer: {
    static: {
      directory: path.join(__dirname, 'ui/public'),
    },
    historyApiFallback: true, // For SPA routing
    hot: true,
    open: false,
    port: 3000,
    proxy: {
      // Optional: proxy API requests to backend during development
      '/api': {
        target: 'http://localhost:8000', // Your Python backend
        changeOrigin: true,
        secure: false,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },

  // Enable source maps in development
  devtool: isProduction ? 'source-map' : 'eval-source-map',

  // Performance hints
  performance: {
    hints: isProduction ? 'warning' : false,
    maxEntrypointSize: 512000,
    maxAssetSize: 512000,
  },

  // Optimization for production
  optimization: {
    splitChunks: {
      chunks: 'all',
      cacheGroups: {
        vendor: {
          test: /[\\/]node_modules[\\/]/,
          name: 'vendors',
          chunks: 'all',
        },
      },
    },
    minimize: isProduction,
  },

  // Stats output control
  stats: {
    assets: true,
    chunks: false,
    children: false,
    modules: false,
    entrypoints: false,
  },
};