import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
for (name, pixels) in [("icon_16x16",16),("icon_16x16@2x",32),("icon_32x32",32),("icon_32x32@2x",64),("icon_128x128",128),("icon_128x128@2x",256),("icon_256x256",256),("icon_256x256@2x",512),("icon_512x512",512),("icon_512x512@2x",1024)] {
    let context = CGContext(data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: pixels * 4, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    context.scaleBy(x: CGFloat(pixels)/1024, y: CGFloat(pixels)/1024)
    let tile = CGPath(roundedRect: CGRect(x: 70,y: 70,width: 884,height: 884), cornerWidth: 210, cornerHeight: 210, transform: nil)
    context.addPath(tile); context.clip()
    let colors = [CGColor(red: 0.34,green: 0.32,blue: 0.68,alpha: 1),CGColor(red: 0.15,green: 0.18,blue: 0.34,alpha: 1)] as CFArray
    let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0,1])!
    context.drawLinearGradient(gradient, start: CGPoint(x: 200,y: 900), end: CGPoint(x: 850,y: 100), options: [])
    // A conversation bubble and checkmark: distinct from Telegram's plane mark.
    let bubble = CGPath(roundedRect: CGRect(x: 235,y: 300,width: 554,height: 430), cornerWidth: 95, cornerHeight: 95, transform: nil)
    context.setFillColor(CGColor(gray: 1, alpha: 0.98)); context.addPath(bubble); context.fillPath()
    let tail = CGMutablePath()
    tail.move(to: CGPoint(x: 330,y: 340)); tail.addLine(to: CGPoint(x: 305,y: 210)); tail.addLine(to: CGPoint(x: 465,y: 335)); tail.closeSubpath()
    context.addPath(tail); context.fillPath()
    context.setStrokeColor(CGColor(red: 0.24,green: 0.27,blue: 0.53,alpha: 1)); context.setLineWidth(45); context.setLineCap(.round); context.setLineJoin(.round)
    context.move(to: CGPoint(x: 385,y: 520)); context.addLine(to: CGPoint(x: 470,y: 435)); context.addLine(to: CGPoint(x: 645,y: 610)); context.strokePath()
    let image = context.makeImage()!
    let destination = CGImageDestinationCreateWithURL(root.appendingPathComponent(name+".png") as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(destination,image,nil); precondition(CGImageDestinationFinalize(destination))
}
