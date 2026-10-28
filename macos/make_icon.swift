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
    let colors = [CGColor(red: 0.10,green: 0.65,blue: 0.96,alpha: 1),CGColor(red: 0.08,green: 0.34,blue: 0.85,alpha: 1)] as CFArray
    let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0,1])!
    context.drawLinearGradient(gradient, start: CGPoint(x: 200,y: 900), end: CGPoint(x: 850,y: 100), options: [])
    let plane = CGMutablePath()
    plane.move(to: CGPoint(x: 230,y: 540)); plane.addLine(to: CGPoint(x: 794,y: 785)); plane.addLine(to: CGPoint(x: 659,y: 250)); plane.addLine(to: CGPoint(x: 492,y: 410)); plane.addLine(to: CGPoint(x: 405,y: 300)); plane.addLine(to: CGPoint(x: 412,y: 475)); plane.closeSubpath()
    context.setFillColor(CGColor(gray: 1, alpha: 0.98)); context.addPath(plane); context.fillPath()
    context.setStrokeColor(CGColor(red: 0.09,green: 0.43,blue: 0.87,alpha: 1)); context.setLineWidth(19); context.setLineCap(.round)
    context.move(to: CGPoint(x: 421,y: 479)); context.addLine(to: CGPoint(x: 690,y: 675)); context.strokePath()
    let image = context.makeImage()!
    let destination = CGImageDestinationCreateWithURL(root.appendingPathComponent(name+".png") as CFURL, UTType.png.identifier as CFString, 1, nil)!
    CGImageDestinationAddImage(destination,image,nil); precondition(CGImageDestinationFinalize(destination))
}
